"""In-memory pilot/failure/pacing integration checks, NOT live API verification."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monitoring.api import ApiError
from monitoring.config import TutorialError
from monitoring.simulation import rounds
from monitoring.workflow import ReadbackPending, RunGuard, measurements, preflight, run
from tests.support import Clock, MemoryClient, environment, fixture


class WorkflowTests(unittest.TestCase):
    def execute(self, client, steps=8, seed=False, read_attempts=1, start_round=1, state_folder=None, destinations_override=None):
        config = client.config
        with tempfile.TemporaryDirectory() as folder, patch("monitoring.workflow.credentials", return_value=destinations_override or environment(config)), \
                patch("monitoring.workflow.time.time", side_effect=client.clock.time), contextlib.redirect_stdout(io.StringIO()):
            log_path = Path(folder) / "fixture.jsonl"
            with RunGuard(state_folder or Path(folder) / "state", now=client.clock.time, sleep=client.clock.sleep) as guard, log_path.open("w", encoding="utf-8") as log:
                run(client, config, rounds(config, start_round=start_round, steps=steps), log, guard, seed_only=seed,
                    read_attempts=read_attempts, sleep=client.clock.sleep, start_round=start_round)
            return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    def test_eight_round_pilot_high_repetition_recovery_and_change_only_status(self):
        client = MemoryClient()
        events = self.execute(client)
        verified = [e for e in events if e["kind"] == "round_verified"]
        self.assertEqual(len(verified), 8)
        self.assertEqual(verified[0]["actual"]["room-a"], "Normal")
        for index in (1, 2, 3):
            self.assertEqual(verified[index]["actual"]["room-a"], "High")
        self.assertEqual(verified[4]["actual"]["room-a"], "Normal")
        self.assertEqual(verified[7]["actual"]["room-a"], "Normal")
        self.assertEqual({v["actual"]["room-b"] for v in verified}, {"Normal"})
        self.assertIn("room-a", verified[2]["unchanged"])
        # Initial two assets + event + recovery; later unchanged rounds mutate nothing.
        mutations = [call for call in client.calls if call[0] == "mutate"]
        self.assertEqual(len(mutations), 3)
        self.assertEqual([len(call[2]) for call in mutations], [2, 1, 1])
        for sid in ("room-a", "room-b"):
            attempts = [call[2] for call in client.calls if call[:2] == ("ingest", sid)]
            self.assertTrue(all(b - a >= 60 - 0.001 for a, b in zip(attempts, attempts[1:])))
        self.assertNotIn("fixture-secret", json.dumps(events))

    def test_model_targets_are_read_each_round_and_change_rule_result(self):
        client = MemoryClient()
        from monitoring import workflow
        original = workflow.event
        def change_target_after_first_round(log, kind, **data):
            original(log, kind, **data)
            if kind == "round_verified" and data["round"] == 1:
                client.assets["room-a"]["z:target"] = 100
        with patch.object(workflow, "event", side_effect=change_target_after_first_round):
            events = self.execute(client, steps=2)
        verified = [e for e in events if e["kind"] == "round_verified"]
        self.assertEqual(verified[1]["actual"]["room-a"], "Normal")

    def test_documented_one_plus_seven_runs_share_model_state_and_pacing(self):
        client = MemoryClient()
        with tempfile.TemporaryDirectory() as folder:
            first = self.execute(client, steps=1, start_round=1, state_folder=Path(folder))
            state = json.loads((Path(folder) / "attempts.json").read_text())
            self.assertEqual(len(state), 2)
            self.assertFalse((Path(folder) / "run.lock").exists())
            second = self.execute(client, steps=7, start_round=2, state_folder=Path(folder))
        verified = [e for e in first + second if e["kind"] == "round_verified"]
        self.assertEqual(len(verified), 8)
        self.assertEqual(verified[2]["actual"]["room-a"], "High")
        self.assertEqual(verified[4]["actual"]["room-a"], "Normal")
        self.assertEqual({e["actual"]["room-b"] for e in verified}, {"Normal"})
        for sid in ("room-a", "room-b"):
            attempts = [call[2] for call in client.calls if call[:2] == ("ingest", sid)]
            self.assertEqual(len(attempts), 8)
            self.assertTrue(all(b - a >= 60 for a, b in zip(attempts, attempts[1:])))
        # Stored Normal is recovered from Tandem across process invocations.
        expected = next(e for e in second if e["kind"] == "rule_expected")
        self.assertEqual(expected["previous"]["room-b"], "Normal")

    def test_element_context_and_unit_contract_prevent_writes(self):
        for field, value in [("context", "t"), ("context", None), ("forgeUnit", "seconds"),
                             ("forgeSpec", "length"), ("forgeUnit", 0)]:
            client = MemoryClient()
            original = client.schema
            def schema(model):
                attrs = original(model)
                attrs["z:noise"][field] = value
                return attrs
            with patch.object(client, "schema", side_effect=schema), self.assertRaises(TutorialError):
                self.execute(client, steps=1)
            self.assertFalse(any(call[0] in {"ingest", "mutate"} for call in client.calls))
        client = MemoryClient()
        original = client.schema
        def mismatched(model):
            attrs = original(model)
            attrs["z:target"]["forgeUnit"] = "meters"
            return attrs
        with patch.object(client, "schema", side_effect=mismatched), self.assertRaisesRegex(TutorialError, "must both be Sound Pressure Level"):
            self.execute(client, steps=1)
        self.assertFalse(any(call[0] == "ingest" for call in client.calls))

    def test_target_change_during_property_readback_prevents_verified_claim(self):
        client = MemoryClient()
        original = client.mutate
        def mutation(model, changes):
            result = original(model, changes)
            client.assets["room-a"]["z:target"] = 1
            return result
        with patch.object(client, "mutate", side_effect=mutation) as mutate, self.assertRaisesRegex(ApiError, "target changed"):
            self.execute(client, steps=1, read_attempts=3)
        self.assertEqual(mutate.call_count, 1)

    def test_delayed_reads_do_not_repeat_any_write(self):
        client = MemoryClient()
        original = client.history
        calls = 0
        def delayed(*args):
            nonlocal calls
            calls += 1
            return [] if calls <= 2 else original(*args)
        with patch.object(client, "history", side_effect=delayed):
            events = self.execute(client, steps=1, read_attempts=3)
        self.assertEqual(sum(call[0] == "ingest" for call in client.calls), 2)
        self.assertEqual(sum(call[0] == "mutate" for call in client.calls), 1)
        self.assertEqual(sum(e["kind"] == "round_verified" for e in events), 1)

    def test_invalid_second_url_prevents_any_ingestion(self):
        client = MemoryClient()
        values = environment(client.config)
        values[client.config["sensors"][1]["ingestion_env"]] = "https://:fixture-secret@example.invalid/"
        with self.assertRaises(TutorialError):
            self.execute(client, steps=1, destinations_override=values)
        self.assertFalse(any(call[0] == "ingest" for call in client.calls))

    def test_auth_failure_during_readback_is_not_polled(self):
        client = MemoryClient()
        with patch.object(client, "history", side_effect=ApiError("Tandem API: HTTP 401")) as history, self.assertRaisesRegex(ApiError, "401"):
            self.execute(client, steps=1, read_attempts=3)
        self.assertEqual(history.call_count, 1)

    def test_concurrent_target_change_prevents_writeback(self):
        client = MemoryClient()
        from monitoring import workflow
        original = workflow.event
        def competing_writer(log, kind, **data):
            original(log, kind, **data)
            if kind == "rule_expected":
                client.assets["room-b"]["z:target"] = 60
        with patch.object(workflow, "event", side_effect=competing_writer), self.assertRaisesRegex(ApiError, "concurrently"):
            self.execute(client, steps=1)
        self.assertFalse(any(call[0] == "mutate" for call in client.calls))

    def test_preflight_bad_second_sensor_prevents_all_writes(self):
        for failure in ("target", "state", "schema", "relationship", "mapping", "model"):
            client = MemoryClient()
            if failure == "target":
                del client.assets["room-b"]["z:target"]
            elif failure == "state":
                client.assets["room-b"]["z:status"] = "Unknown"
            elif failure == "schema":
                original = client.schema
                client.schema = lambda model: {k: v for k, v in original(model).items() if k != "z:status"}
            elif failure == "relationship":
                original = client.scan
                def scan(*args):
                    rows = original(*args)
                    if args[0] == client.default:
                        rows[-1]["x:r"] = ""
                    return rows
                client.scan = scan
            elif failure == "mapping":
                client.stream_configs = lambda model: {}
            else:
                client.models = [client.default]
            with self.subTest(failure=failure), self.assertRaises(TutorialError):
                self.execute(client, steps=1)
            self.assertFalse(any(call[0] in {"ingest", "mutate"} for call in client.calls))

    def test_legacy_model_status_blocks_all_live_writes_without_conversion(self):
        client = MemoryClient()
        client.assets["room-b"].update({"z:status": "AVAILABLE"})
        with self.assertRaisesRegex(TutorialError, "not a schema-defined"):
            self.execute(client, steps=1)
        self.assertFalse(any(call[0] in {"ingest", "mutate"} for call in client.calls))
        self.assertEqual(client.assets["room-b"]["z:status"], "AVAILABLE")

    def test_partial_second_ingestion_failure_stops_without_mutation_or_retry(self):
        client = MemoryClient()
        original = client.ingest
        attempts = []
        def ingest(target, payload):
            attempts.append(payload)
            if len(attempts) == 2:
                raise ApiError("Synthetic timeout; delivery unknown.")
            original(target, payload)
        client.ingest = ingest
        with self.assertRaises(ApiError):
            self.execute(client, steps=2)
        self.assertEqual(len(attempts), 2)
        self.assertFalse(any(call[0] == "mutate" for call in client.calls))

    def test_missing_or_mismatched_history_never_writes_status(self):
        for bad in ([], [(1, 99)]):
            client = MemoryClient()
            client.history = lambda *args: bad
            with self.assertRaises(ApiError):
                self.execute(client, steps=1, read_attempts=2)
            self.assertFalse(any(call[0] == "mutate" for call in client.calls))

    def test_unknown_mutation_delivery_attempted_once(self):
        client = MemoryClient()
        with patch.object(client, "mutate", side_effect=ApiError("Synthetic unknown delivery")) as mutate, self.assertRaises(ApiError):
            self.execute(client, steps=2)
        self.assertEqual(mutate.call_count, 1)

    def test_second_model_failure_leaves_explicit_partial_state_without_verified_round(self):
        from monitoring import workflow
        from tests.support import encoded
        client = MemoryClient()
        second_model = "urn:adsk.dtm:" + encoded(b"n" * 16)
        client.config["sensors"][1]["asset"]["model_urn"] = second_model
        client.models.append(second_model)
        original = client.mutate
        def partial(model, changes):
            if model == second_model:
                raise ApiError("Synthetic second-model failure; first-model changes remain.")
            return original(model, changes)
        with patch.object(client, "mutate", side_effect=partial) as mutate, \
                patch.object(workflow, "event", wraps=workflow.event) as audit, self.assertRaises(ApiError):
            self.execute(client, steps=1)
        self.assertEqual(mutate.call_count, 2)
        self.assertEqual(client.assets["room-a"]["z:status"], "Normal")
        self.assertNotIn("z:status", client.assets["room-b"])
        self.assertFalse(any(call.args[1] == "round_verified" for call in audit.call_args_list))

    def test_property_readback_mismatch_is_explicit(self):
        client = MemoryClient()
        with patch.object(client, "mutate", return_value=123) as mutate, self.assertRaises(ReadbackPending):
            self.execute(client, steps=1, read_attempts=2)
        self.assertEqual(mutate.call_count, 1)

    def test_seed_populates_payload_only_without_mapping_or_rule_claim(self):
        client = MemoryClient()
        client.stream_configs = lambda model: {}
        events = self.execute(client, steps=1, seed=True)
        self.assertEqual(sum(call[0] == "ingest" for call in client.calls), 2)
        self.assertFalse(any(call[0] in {"history", "mutate"} for call in client.calls))
        self.assertFalse(any(event["kind"] == "round_verified" for event in events))
        self.assertEqual(events[-1]["kind"], "mapping_sample_complete")

    def test_persistent_pacing_survives_restart_and_failed_attempt(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as folder:
            with RunGuard(folder, now=clock.time, sleep=clock.sleep) as guard:
                guard.reserve("model", "stream")
                first = clock.time()
                # A competing process cannot share the run directory.
                with self.assertRaises(TutorialError):
                    with RunGuard(folder):
                        pass
            with RunGuard(folder, now=clock.time, sleep=clock.sleep) as guard:
                guard.reserve("model", "stream")
                self.assertGreaterEqual(clock.time() - first, 60)
            self.assertFalse((Path(folder) / "run.lock").exists())
        for interval in [0, 59, float("nan"), float("inf")]:
            with self.assertRaises(TutorialError):
                RunGuard(interval=interval)

    def test_slow_request_completion_and_restart_preserve_full_interval(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as folder:
            with RunGuard(folder, now=clock.time, sleep=clock.sleep) as guard:
                guard.reserve("model", "stream")
                clock.value += 40  # Pretend disk/network blocked for forty seconds.
                guard.complete("model", "stream")
                completed = clock.time()
            with RunGuard(folder, now=clock.time, sleep=clock.sleep) as guard:
                guard.reserve("model", "stream")
                self.assertGreaterEqual(clock.time() - completed, 60)

    def test_stored_status_survives_new_pilot_process(self):
        client = MemoryClient()
        self.execute(client, steps=1)
        first = dict(client.assets["room-a"])
        count = sum(call[0] == "mutate" for call in client.calls)
        events = self.execute(client, steps=1)
        self.assertEqual(client.assets["room-a"], first)
        self.assertEqual(sum(call[0] == "mutate" for call in client.calls), count)
        verified = next(e for e in events if e["kind"] == "round_verified")
        self.assertEqual(verified["unchanged"], ["room-a", "room-b"])

    def test_clock_rollback_and_corrupt_pacing_state_stop_safely(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "attempts.json"
            path.write_text(json.dumps({"m/s": clock.time() + 60}))
            with RunGuard(folder, now=clock.time, sleep=clock.sleep) as guard, self.assertRaises(TutorialError):
                guard.reserve("m", "s")
            path.write_text("{invalid")
            with self.assertRaises(TutorialError):
                with RunGuard(folder):
                    pass
            self.assertFalse((Path(folder) / "run.lock").exists())

    def test_read_access_allows_mapping_bootstrap_but_blocks_pilot_before_send(self):
        client = MemoryClient()
        client.access_level = "Read"
        client.stream_configs = lambda model: {}
        events = self.execute(client, steps=1, seed=True)
        self.assertEqual([c[3] for c in client.calls if c[0] == "ingest"],
                         [{"noise_db": 45.0}, {"noise_db": 40.0}])
        self.assertFalse(any(c[0] in {"history", "mutate"} for c in client.calls))
        outcomes = [e for e in events if e["kind"] == "ingest_outcome"]
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(e["http_status"] == 200 and e["outcome"] == "HTTP_ACCEPTED" for e in outcomes))
        self.assertTrue(all(e["send_started_utc"] <= e["send_ended_utc"] and e["send_started_utc"].endswith("+00:00") for e in outcomes))
        client = MemoryClient()
        client.access_level = "Read"
        with self.assertRaisesRegex(TutorialError, "Users > Services"):
            self.execute(client, steps=1)
        self.assertFalse(any(c[0] in {"ingest", "mutate"} for c in client.calls))

    def test_mapping_samples_first_unknown_still_attempts_second_once_without_rule(self):
        client = MemoryClient()
        original = client.ingest
        attempts = []
        def ingest(target, payload):
            attempts.append(payload)
            if len(attempts) == 1:
                raise ApiError("Ingestion: network failure; delivery unknown. No retry.")
            return original(target, payload)
        with patch.object(client, "ingest", side_effect=ingest):
            events = self.execute(client, steps=1, seed=True)
        self.assertEqual(attempts, [{"noise_db": 45.0}, {"noise_db": 40.0}])
        outcomes = [e for e in events if e["kind"] == "ingest_outcome"]
        self.assertEqual([e["outcome"] for e in outcomes], ["DELIVERY_UNKNOWN", "HTTP_ACCEPTED"])
        self.assertFalse(any(c[0] in {"history", "mutate"} for c in client.calls))
        self.assertFalse(any(e["kind"] == "round_verified" for e in events))

    def test_mapping_http_failure_is_distinct_from_unknown_and_no_resend(self):
        client = MemoryClient()
        attempts = []
        def ingest(target, payload):
            attempts.append(payload)
            raise ApiError("Ingestion: HTTP 403; no retry.", http_status=403)
        with patch.object(client, "ingest", side_effect=ingest):
            events = self.execute(client, steps=1, seed=True)
        self.assertEqual(len(attempts), 2)
        outcomes = [e for e in events if e["kind"] == "ingest_outcome"]
        self.assertEqual([e["http_status"] for e in outcomes], [403, 403])
        self.assertTrue(all(e["outcome"] == "HTTP_ERROR" for e in outcomes))

    def test_host_and_rooms_are_checked_separately_even_for_mapping_setup(self):
        for column in ("x:p", "x:r"):
            client = MemoryClient()
            original = client.scan
            def scan(*args):
                rows = original(*args)
                if args[0] == client.default:
                    rows[1][column] = ""
                return rows
            with patch.object(client, "scan", side_effect=scan), self.assertRaisesRegex(TutorialError, "Both Host"):
                self.execute(client, steps=1, seed=True)
            self.assertFalse(any(c[0] == "ingest" for c in client.calls))

    def test_room_identity_classification_and_comments_prevent_wrong_destinations(self):
        for field, value in (("n:n", "Wrong Room"), ("r:number", "999"),
                             ("r:comments", "Unrelated"), ("n:!v", "Wrong class")):
            client = MemoryClient()
            client.assets["room-b"][field] = value
            with self.assertRaises(TutorialError):
                self.execute(client, steps=1, seed=True)
            self.assertFalse(any(c[0] == "ingest" for c in client.calls))

    def test_encoded_status_readback_and_equality_do_not_repeat_mutation(self):
        client = MemoryClient()
        client.assets["room-a"]["z:status"] = 1
        client.assets["room-b"]["z:status"] = "1"
        client.config["sensors"][0]["simulation"]["values"][0] = 55.0
        events = self.execute(client, steps=1)
        self.assertFalse(any(c[0] == "mutate" for c in client.calls))
        self.assertEqual(next(e for e in events if e["kind"] == "round_verified")["actual"],
                         {"room-a": "Normal", "room-b": "Normal"})
