"""Offline UI-run orchestration, cancellation, pacing and reconciliation tests."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from monitoring.api import ApiError
from monitoring.config import TutorialError
from monitoring.execution import Controller, availability, custom_batch, planned
from monitoring.workflow import RunGuard
from tests.support import MemoryClient, environment

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = MemoryClient()
        self.controller = Controller(self.root/"state", self.root/"outputs", lambda *a, **k:self.client,
                                     now=self.client.clock.time, sleep=self.client.clock.sleep)
        self.patches = [patch("monitoring.workflow.credentials", return_value=environment(self.client.config)),
                        patch("monitoring.workflow.time.time", side_effect=self.client.clock.time),
                        contextlib.redirect_stdout(io.StringIO())]
        for p in self.patches:
            p.__enter__()
            self.addCleanup(p.__exit__, None, None, None)
    def finish(self):
        self.controller.thread.join(5)
        self.assertFalse(self.controller.thread.is_alive())
        return self.controller.status()
    def events(self):
        return [json.loads(line) for p in (self.root/"outputs").glob("*.jsonl") for line in p.read_text().splitlines()]
    def test_guided_eight_rounds_reuses_verified_pipeline_and_spacing(self):
        self.controller.start(self.client.config, "guided")
        status = self.finish()
        self.assertEqual((status["phase"],status["completed"]), ("Completed",8))
        events = [e for e in self.events() if e["kind"]=="round_verified"]
        self.assertEqual([e["actual"]["room-a"] for e in events], ["Normal","High","High","High","Normal","Normal","Normal","Normal"])
        self.assertTrue(all(e["actual"]["room-b"]=="Normal" for e in events))
        for sid in ("room-a","room-b"):
            stamps=[c[2] for c in self.client.calls if c[:2]==("ingest",sid)]
            self.assertEqual(len(stamps),8)
            self.assertTrue(all(b-a>=60 for a,b in zip(stamps,stamps[1:])))
        self.assertFalse((self.root/"state/review.json").exists())
    def test_custom_high_and_recovery_and_cooldown_no_queued_send(self):
        self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
        self.assertEqual(self.finish()["verified"],{"room-a":"High","room-b":"Normal"})
        count=len(self.client.calls)
        with self.assertRaisesRegex(TutorialError,"Cooling down"):
            self.controller.start(self.client.config,"custom",{"room-a":45.0,"room-b":40.0})
        self.assertEqual(count,len(self.client.calls))
        self.assertGreater(availability(self.client.config,self.root/"state",self.client.clock.time)["waits"]["room-a"],0)
        self.client.clock.value+=61
        self.controller.start(self.client.config,"custom",{"room-a":45.0,"room-b":40.0})
        self.assertEqual(self.finish()["verified"],{"room-a":"Normal","room-b":"Normal"})
        payloads=[c[3] for c in self.client.calls if c[0]=="ingest"]
        self.assertEqual(payloads,[{"noise_db":60.0},{"noise_db":40.0},{"noise_db":45.0},{"noise_db":40.0}])
    def test_duplicate_start_other_session_and_cli_excluded(self):
        entered,release=threading.Event(),threading.Event()
        original=self.client.facility
        def blocked(*args):
            entered.set()
            release.wait(3)
            return original(*args)
        with patch.object(self.client,"facility",side_effect=blocked):
            self.controller.start(self.client.config,"guided")
            self.assertTrue(entered.wait(2))
            try:
                with self.assertRaises(TutorialError):
                    self.controller.start(self.client.config,"guided")
                other=Controller(self.root/"state",self.root/"outputs")
                with self.assertRaises(TutorialError):
                    other.start(self.client.config,"guided")
                with self.assertRaises(TutorialError):
                    with RunGuard(self.root/"state"): pass
                self.controller.stop()
            finally: release.set()
            status=self.finish()
        self.assertIn("Interrupted",status["phase"])
        self.assertFalse(any(c[0] in ("ingest","mutate") for c in self.client.calls))
    def test_stop_after_first_send_prevents_second_send_and_all_mutations(self):
        original=self.client.ingest
        def stop_after(*args):
            result=original(*args)
            self.controller.stop()
            return result
        with patch.object(self.client,"ingest",side_effect=stop_after):
            self.controller.start(self.client.config,"guided")
            status=self.finish()
        self.assertEqual(status["completed"],0)
        self.assertIn("Interrupted",status["phase"])
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),1)
        self.assertFalse(any(c[0]=="mutate" for c in self.client.calls))
        self.assertFalse((self.root/"state/review.json").exists())
        self.assertTrue(any(e["kind"]=="operation_reconciled" for e in self.events()))
    def test_stop_in_pacing_wait_does_not_start_next_round(self):
        def sleep(seconds):
            self.controller.stop()
            self.client.clock.sleep(seconds)
        self.controller.sleep=sleep
        self.controller.start(self.client.config,"guided")
        status=self.finish()
        self.assertEqual(status["completed"],1)
        self.assertIn("Interrupted",status["phase"])
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),2)
        self.assertFalse((self.root/"state/review.json").exists())
    def test_unknown_delivery_never_resends_and_survives_controller_restart(self):
        with patch.object(self.client,"ingest",side_effect=ApiError("Delivery unknown")) as ingest:
            self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
            status=self.finish()
        self.assertIn("unresolved",status["phase"])
        self.assertEqual(ingest.call_count,1)
        fresh=Controller(self.root/"state",self.root/"outputs",lambda *a,**k:self.client, now=self.client.clock.time)
        with self.assertRaises(TutorialError):
            fresh.start(self.client.config,"guided")
        fresh.retry_verification(self.client.config)
        fresh.thread.join(5)
        self.assertIn("unknown",fresh.status()["issue"])
        self.assertTrue((self.root/"state/review.json").exists())
    def test_stop_during_first_mutation_prevents_further_model_writes(self):
        original=self.client.mutate
        def mutation(*args):
            result=original(*args)
            self.controller.stop()
            return result
        with patch.object(self.client,"mutate",side_effect=mutation):
            self.controller.start(self.client.config,"guided")
            status=self.finish()
        self.assertEqual(status["phase"],"Round 1 verified; remaining rounds were not restarted.")
        self.assertEqual(sum(c[0]=="mutate" for c in self.client.calls),1)
        self.assertEqual(status["completed"],1)
    def test_preview_uses_passed_model_targets_and_inputs_are_validated(self):
        targets={"room-a":70.0,"room-b":50.0}
        preview=planned(self.client.config,targets)
        self.assertTrue(all(r["Expected status"]=="Normal" for r in preview))
        for value in (float("nan"),float("inf"),True,45.12,"60"):
            with self.assertRaises(TutorialError):
                custom_batch(self.client.config,{"room-a":value,"room-b":40.0})

    def test_stop_during_readback_poll_prevents_mutation(self):
        def empty(*args):
            self.controller.stop()
            return []
        with patch.object(self.client,"history",side_effect=empty):
            self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
            status=self.finish()
        self.assertEqual(status["completed"],0)
        self.assertIn("unresolved",status["phase"])
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),2)
        self.assertFalse(any(c[0]=="mutate" for c in self.client.calls))
        self.assertTrue((self.root/"state/review.json").exists())

    def test_rejected_request_is_reviewed_with_reads_before_explicit_acknowledgement(self):
        with patch.object(self.client,"ingest",side_effect=ApiError("Rejected",http_status=404)):
            self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
            self.finish()
        self.assertIn("HTTP 404",self.controller.status()["phase"])
        self.assertTrue(any(c[0]=="history" for c in self.client.calls))
        self.assertFalse((self.root/"state/review.json").exists())

    def test_delayed_measurement_retry_finishes_without_new_ingestion(self):
        original=self.client.history
        with patch.object(self.client,"history",return_value=[]):
            self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
            self.finish()
        self.assertTrue((self.root/"state/review.json").exists())
        sent=sum(c[0]=="ingest" for c in self.client.calls)
        self.controller.retry_verification(self.client.config)
        status=self.finish()
        self.assertEqual(status["phase"],"Completed")
        self.assertEqual(status["verified"],{"room-a":"High","room-b":"Normal"})
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),sent)
        self.assertFalse((self.root/"state/review.json").exists())

    def test_unknown_mutation_delivery_readback_never_repeats_write(self):
        original=self.client.mutate
        def timeout(*args):
            original(*args)
            raise ApiError("Delivery unknown")
        with patch.object(self.client,"mutate",side_effect=timeout) as mutate:
            self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
            status=self.finish()
        self.assertEqual(mutate.call_count,1)
        self.assertEqual(status["phase"],"Completed")
        self.assertFalse((self.root/"state/review.json").exists())

    def test_status_mismatch_retry_is_read_only(self):
        with patch.object(self.client,"mutate",return_value=123):
            self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
            self.finish()
        self.assertIn("stored status",self.controller.status()["issue"])
        self.client.assets["room-a"]["z:status"]="High"
        self.client.assets["room-b"]["z:status"]="Normal"
        before=sum(c[0] in ("ingest","mutate") for c in self.client.calls)
        self.controller.retry_verification(self.client.config)
        self.assertEqual(self.finish()["phase"],"Completed")
        self.assertEqual(sum(c[0] in ("ingest","mutate") for c in self.client.calls),before)
