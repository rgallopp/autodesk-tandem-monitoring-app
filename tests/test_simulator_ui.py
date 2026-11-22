"""Offline Streamlit simulator interactions; fixture destinations only."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from monitoring.api import ApiError
from monitoring.config import ROOT, TutorialError
from monitoring.execution import Controller
from tests.support import MemoryClient, environment

class SimulatorUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client=MemoryClient()
        self.controller=Controller(Path(self.temp.name)/"state",Path(self.temp.name)/"outputs",
                                   lambda *a,**k:self.client,now=self.client.clock.time,sleep=self.client.clock.sleep)
        patches=[patch("monitoring.config.load",return_value=self.client.config),
                 patch("monitoring.simulator_ui.load",return_value=self.client.config),
                 patch("monitoring.api.TandemClient",return_value=self.client),
                 patch("monitoring.simulator_ui.CONTROLLER",self.controller),
                 patch("monitoring.execution.CONTROLLER",self.controller),
                 patch("monitoring.workflow.credentials",return_value=environment(self.client.config)),
                 patch("monitoring.workflow.time.time",side_effect=self.client.clock.time)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
    def button(self,app,label):
        return next(b for b in app.button if b.label==label)
    def app(self):
        return AppTest.from_file(str(ROOT/"app.py"),default_timeout=30).run()
    def test_preview_and_reruns_do_not_send_and_targets_are_model_read(self):
        self.client.assets["room-a"]["z:target"]=70.0
        app=self.app()
        self.button(app,"Preview").click().run()
        self.assertFalse(app.exception)
        planned=next(df.value for df in app.dataframe if "Expected status" in df.value.columns)
        self.assertEqual(len(planned),16)
        self.assertEqual(planned["Checkpoint"].unique().tolist(),
                         ["Before the event", "During the event", "After recovery"])
        self.assertTrue(all(planned["Expected status"]=="Normal"))
        app.run()
        self.button(app,"Refresh").click().run()
        self.assertFalse(any(c[0] in ("ingest","mutate") for c in self.client.calls))
        self.assertEqual(sum(e.label=="Simulator" for e in app.expander),1)
    def test_custom_send_refresh_reads_tandem_and_cooldown_enables_button(self):
        app=self.app()
        app.radio[0].set_value("Try your own readings").run()
        self.assertEqual([n.value for n in app.number_input],[45.0,40.0])
        app.number_input[0].set_value(60.0).run()
        app.number_input[1].set_value(50.0).run()
        expected = [c.value for c in app.caption if c.value.startswith("Expected status")]
        self.assertEqual(expected, ["Expected status: High", "Expected status: Normal"])
        reads = sum(c[0] == "history" for c in self.client.calls)
        self.button(app, "Send readings").click().run()
        self.controller.thread.join(5)
        app.run()
        self.assertFalse(app.exception)
        captions = [c.value for c in app.caption]
        self.assertEqual(sum("Reading accepted" in c for c in captions), 2)
        self.assertIn("Computer Lab A 109: Room status updated to High.", captions)
        self.assertEqual(sum(c.startswith("Ready to send in") for c in captions), 1)
        self.assertTrue(self.button(app, "Send readings").disabled)
        self.assertEqual(sum(c[0] == "history" for c in self.client.calls), reads)
        self.assertIsNone(app.session_state["result"]["cards"][0]["measurement"])

        with patch.object(self.client, "history", return_value=[]):
            self.button(app, "Refresh").click().run()
        self.assertIsNone(app.session_state["result"]["cards"][0]["measurement"])
        self.assertIn("Stored Noise Status: High", " ".join(m.value for m in app.markdown))
        self.button(app, "Refresh").click().run()
        self.assertEqual(app.session_state["result"]["cards"][0]["measurement"], 60.0)
        self.client.clock.value += 61
        app.run()
        self.assertFalse(self.button(app, "Send readings").disabled)
        self.assertEqual(sum(c[0] == "ingest" for c in self.client.calls), 2)

    def test_guided_button_runs_scenario_once_and_reruns_only_read(self):
        app=self.app()
        self.button(app,"Start demo").click().run()
        self.controller.thread.join(5)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.controller.status()["completed"],8)
        count=sum(c[0]=="ingest" for c in self.client.calls)
        app.run()
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),count)
        self.button(app, "Refresh").click().run()
        self.assertEqual(app.session_state["result"]["cards"][0]["stored_status"],"Normal")
    def test_stop_remains_accessible_if_dashboard_read_fails(self):
        self.controller.update(active=True,phase="Sending readings")
        with patch.object(self.client, "history", side_effect=TutorialError("No history")):
            app=self.app()
        self.assertFalse(app.exception)
        app.radio[0].set_value("Try your own readings").run()
        self.assertEqual([c.value for c in app.caption if c.value.startswith("Expected status")],
                         ["Expected status: Normal", "Expected status: Normal"])
        self.assertFalse(self.button(app,"Stop").disabled)
        self.button(app,"Stop").click().run()
        self.assertTrue(self.controller.stop_event.is_set())
        self.assertFalse(any(c[0]=="ingest" for c in self.client.calls))

    def test_failed_writeback_and_other_lab_results_are_visible(self):
        app = self.app()
        app.radio[0].set_value("Try your own readings").run()
        app.number_input[1].set_value(80.0).run()
        original = self.client.mutate

        def mutate(model, changes):
            if changes[0][0] == self.client.assets["room-a"]["k"]:
                raise ApiError("Synthetic HTTP 403", http_status=403)
            return original(model, changes)

        with patch.object(self.client, "mutate", side_effect=mutate) as mutation:
            self.button(app, "Send readings").click().run()
            self.controller.thread.join(5)
            app.run()
        self.assertEqual(mutation.call_count, 2)
        self.assertEqual(self.controller.status()["phase"], "Finished with errors")
        captions = [c.value for c in app.caption]
        self.assertEqual(sum("Reading accepted" in c for c in captions), 2)
        self.assertIn("Computer Lab B 210: Room status updated to High.", captions)
        self.assertIn("Computer Lab A 109: Status update failed. Synthetic HTTP 403", [e.value for e in app.error])
        self.assertNotIn("z:status", self.client.assets["room-a"])
        self.assertEqual(self.client.assets["room-b"]["z:status"], "High")

    def test_uncertain_reading_is_visible_without_status_write_or_retry(self):
        app = self.app()
        app.radio[0].set_value("Try your own readings").run()
        original = self.client.ingest

        def ingest(destination, payload):
            if destination[0].endswith(self.client.config["sensors"][0]["connection_key"]):
                raise ApiError("Synthetic gateway timeout", http_status=504)
            return original(destination, payload)

        with patch.object(self.client, "ingest", side_effect=ingest) as send:
            self.button(app, "Send readings").click().run()
            self.controller.thread.join(5)
            app.run()
        self.assertEqual(send.call_count, 2)
        self.assertIn("Computer Lab A 109: Reading delivery uncertain. Synthetic gateway timeout",
                      [message.value for message in app.warning])
        self.assertNotIn("z:status", self.client.assets["room-a"])
        self.assertEqual(self.client.assets["room-b"]["z:status"], "Normal")

    def test_legacy_review_marker_does_not_gate_new_sends(self):
        self.controller.folder.mkdir()
        (self.controller.folder / "review.json").write_text("{}")
        app = self.app()
        labels = [button.label for button in app.button]
        self.assertFalse(self.button(app, "Start demo").disabled)
        self.assertNotIn("Retry verification", labels)
        self.assertNotIn("Check interrupted run", labels)
        self.assertFalse(any(c[0] == "ingest" for c in self.client.calls))
