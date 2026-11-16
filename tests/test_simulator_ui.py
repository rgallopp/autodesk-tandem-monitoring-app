"""Offline Streamlit simulator interactions; fixture destinations only."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from monitoring.config import ROOT, TutorialError
from monitoring.execution import Controller, availability
from monitoring.dashboard import snapshot
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
                 patch("monitoring.simulator_ui.TandemClient",return_value=self.client),
                 patch("monitoring.simulator_ui.CONTROLLER",self.controller),
                 patch("monitoring.execution.CONTROLLER",self.controller),
                 patch("monitoring.simulator_ui.availability",side_effect=lambda c:availability(c,self.controller.folder,self.client.clock.time)),
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
        self.assertTrue(all(planned["Expected status"]=="Normal"))
        app.run()
        self.button(app,"Refresh").click().run()
        self.assertFalse(any(c[0] in ("ingest","mutate") for c in self.client.calls))
        self.assertEqual(sum(e.label=="Simulator" for e in app.expander),1)
    def test_custom_send_refresh_verified_data_and_cooldown(self):
        app=self.app()
        app.radio[0].set_value("Try your own readings").run()
        self.assertEqual([n.value for n in app.number_input],[45.0,40.0])
        app.number_input[0].set_value(60.0).run()
        self.button(app,"Send readings").click().run()
        self.controller.thread.join(5)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(self.controller.status()["verified"],{"room-a":"High","room-b":"Normal"})
        self.assertTrue(self.button(app,"Send readings").disabled)
        current=app.session_state["result"]
        self.assertEqual(current["cards"][0]["measurement"],60.0)
        self.assertEqual(current["cards"][0]["stored_status"],"High")
        count=sum(c[0]=="ingest" for c in self.client.calls)
        app.run()
        self.button(app,"Refresh").click().run()
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),count)
        self.client.clock.value+=61
        app.run()
        self.assertFalse(self.button(app,"Send readings").disabled)
        self.assertEqual(sum(c[0]=="ingest" for c in self.client.calls),2)
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
        self.assertEqual(app.session_state["result"]["cards"][0]["stored_status"],"Normal")
    def test_stop_remains_accessible_if_dashboard_read_fails(self):
        self.controller.update(active=True,phase="Waiting for stored readings")
        with patch("monitoring.dashboard.snapshot",side_effect=TutorialError("No read")):
            app=self.app()
        self.assertFalse(app.exception)
        self.assertFalse(self.button(app,"Stop").disabled)
        self.button(app,"Stop").click().run()
        self.assertTrue(self.controller.stop_event.is_set())
        self.assertFalse(any(c[0]=="ingest" for c in self.client.calls))

    def test_retry_button_only_for_unresolved_operations(self):
        app=self.app()
        labels=[b.label for b in app.button]
        self.assertNotIn("Retry verification",labels)
        self.assertNotIn("Check interrupted run",labels)
        self.assertNotIn("Acknowledge reviewed partial run",labels)
        self.controller.update(issue="Lab 109: recorded reading not returned by Tandem yet.")
        with patch("monitoring.simulator_ui.availability",return_value={"waits":{"room-a":0,"room-b":0},"busy":False,"review":True}), patch.object(self.controller,"retry_verification") as retry:
            app.run()
            self.assertTrue(any("Lab 109" in x.value for x in app.info))
            self.assertTrue(self.button(app,"Start demo").disabled)
            self.button(app,"Retry verification").click().run()
            retry.assert_called_once()
            app.run()
            retry.assert_called_once()
        self.assertFalse(any(c[0]=="ingest" for c in self.client.calls))
