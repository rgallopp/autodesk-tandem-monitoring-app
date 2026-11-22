"""Offline UI-run orchestration, cancellation, pacing and per-lab outcomes tests."""
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
                        patch("monitoring.workflow.time.time", side_effect=self.client.clock.time)]
        for p in self.patches:
            p.__enter__()
            self.addCleanup(p.__exit__, None, None, None)
    def finish(self):
        self.controller.thread.join(5)
        self.assertFalse(self.controller.thread.is_alive())
        return self.controller.status()
    def events(self):
        return [json.loads(line) for p in (self.root/"outputs").glob("*.jsonl") for line in p.read_text().splitlines()]
    def test_guided_eight_rounds_reuses_shared_pipeline_and_spacing(self):
        self.controller.start(self.client.config, "guided")
        status = self.finish()
        self.assertEqual((status["phase"],status["completed"]), ("Completed",8))
        events = [e for e in self.events() if e["kind"] == "status_outcome"]
        self.assertEqual([e["status"] for e in events if e["sensor"] == "room-a"],
                         ["Normal", "High", "High", "High", "Normal", "Normal", "Normal", "Normal"])
        self.assertEqual([e["status"] for e in events if e["sensor"] == "room-b"], ["Normal"] * 8)
        self.assertFalse(any(c[0] == "history" for c in self.client.calls))
        for sid in ("room-a","room-b"):
            stamps=[c[2] for c in self.client.calls if c[:2]==("ingest",sid)]
            self.assertEqual(len(stamps),8)
            self.assertTrue(all(b-a>=60 for a,b in zip(stamps,stamps[1:])))
    def test_custom_high_and_recovery_and_cooldown_no_queued_send(self):
        self.controller.start(self.client.config,"custom",{"room-a":60.0,"room-b":40.0})
        self.assertEqual({sid: lab["status_outcome"]["status"] for sid, lab in self.finish()["outcomes"].items()},{"room-a":"High","room-b":"Normal"})
        count=len(self.client.calls)
        with self.assertRaisesRegex(TutorialError,"Cooling down"):
            self.controller.start(self.client.config,"custom",{"room-a":45.0,"room-b":40.0})
        self.assertEqual(count,len(self.client.calls))
        self.assertGreater(availability(self.client.config,self.root/"state",self.client.clock.time)["waits"]["room-a"],0)
        self.client.clock.value+=61
        self.controller.start(self.client.config,"custom",{"room-a":45.0,"room-b":40.0})
        self.assertEqual({sid: lab["status_outcome"]["status"] for sid, lab in self.finish()["outcomes"].items()},{"room-a":"Normal","room-b":"Normal"})
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
        self.assertEqual(status["phase"], "Stopped")
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
        self.assertEqual(status["phase"], "Stopped")
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),1)
        self.assertFalse(any(c[0]=="mutate" for c in self.client.calls))
        self.assertEqual(status["outcomes"]["room-a"]["ingest_outcome"]["outcome"], "HTTP_ACCEPTED")
    def test_stop_in_pacing_wait_does_not_start_next_round(self):
        def sleep(seconds):
            self.controller.stop()
            self.client.clock.sleep(seconds)
        self.controller.sleep=sleep
        self.controller.start(self.client.config,"guided")
        status=self.finish()
        self.assertEqual(status["completed"],1)
        self.assertEqual(status["phase"], "Stopped")
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),2)
    def test_unknown_delivery_never_resends_or_writes_status_for_that_lab(self):
        original = self.client.ingest
        with patch.object(self.client, "ingest", side_effect=[ApiError("Delivery unknown"),
                                                             200]) as ingest:
            self.controller.start(self.client.config, "guided")
            status = self.finish()
        self.assertEqual(status["phase"], "Finished with errors")
        self.assertEqual(status["completed"], 1)
        self.assertEqual(ingest.call_count, 2)
        first, second = (status["outcomes"][sid] for sid in ("room-a", "room-b"))
        self.assertEqual(first["ingest_outcome"]["outcome"], "DELIVERY_UNKNOWN")
        self.assertNotIn("status_outcome", first)
        self.assertEqual(second["status_outcome"]["outcome"], "STATUS_UPDATED")
        self.assertNotIn("z:status", self.client.assets["room-a"])
        self.assertEqual(self.client.assets["room-b"]["z:status"], "Normal")
        self.assertFalse(any(c[0] == "history" for c in self.client.calls))
        self.client.clock.value += 60
        fresh = Controller(self.root / "state", self.root / "outputs", lambda *a, **k: self.client,
                           now=self.client.clock.time)
        with patch.object(self.client, "ingest", wraps=original) as ingest:
            fresh.start(self.client.config, "custom", {"room-a": 55.0, "room-b": 90.0})
            fresh.thread.join(5)
        self.assertEqual(ingest.call_count, 2)
        self.assertEqual([a["z:status"] for a in self.client.assets.values()], ["Normal", "High"])

    def test_stop_during_first_mutation_prevents_further_model_writes(self):
        original=self.client.mutate
        def mutation(*args):
            result=original(*args)
            self.controller.stop()
            return result
        with patch.object(self.client,"mutate",side_effect=mutation):
            self.controller.start(self.client.config,"guided")
            status=self.finish()
        self.assertEqual(status["phase"], "Stopped")
        self.assertEqual(sum(c[0]=="mutate" for c in self.client.calls),1)
        self.assertEqual(status["completed"],0)
        self.assertEqual(status["outcomes"]["room-a"]["status_outcome"]["outcome"], "STATUS_UPDATED")
    def test_preview_uses_passed_model_targets_and_inputs_are_validated(self):
        targets={"room-a":70.0,"room-b":50.0}
        preview=planned(self.client.config,targets)
        self.assertTrue(all(r["Expected status"]=="Normal" for r in preview))
        for value in (float("nan"),float("inf"),True,45.12,"60"):
            with self.assertRaises(TutorialError):
                custom_batch(self.client.config,{"room-a":value,"room-b":40.0})
