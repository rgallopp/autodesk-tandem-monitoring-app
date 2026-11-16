"""Offline API-only display and real-timestamp decision support fixtures."""

import unittest
from unittest.mock import patch

from monitoring.config import ROOT, TutorialError
from monitoring.dashboard import snapshot
from tests.support import MemoryClient
from tests import test_workflow


class AppTests(unittest.TestCase):
    def seeded(self, steps=2):
        client = MemoryClient()
        test_workflow.WorkflowTests().execute(client, steps=steps)
        return client

    def read(self, client, **kwargs):
        return snapshot(client, client.config, now_ms=int(client.clock.time() * 1000), **kwargs)

    def test_snapshot_reads_api_targets_status_and_actual_timestamps_only(self):
        client = self.seeded()
        before = len([c for c in client.calls if c[0] in {"ingest", "mutate"}])
        data = self.read(client)
        self.assertEqual(data["source"], "Autodesk Tandem API")
        self.assertEqual(data["high_labs"], ["Computer Lab A 109"])
        a, b = data["cards"]
        self.assertEqual((a["measurement"], a["target"], a["stored_status"]), (66.3, 55, "High"))
        self.assertEqual(b["stored_status"], "Normal")
        self.assertIn("+00:00", a["ingested_utc"])
        self.assertEqual(before, len([c for c in client.calls if c[0] in {"ingest", "mutate"}]))

    def test_actual_sentinel_reading_has_no_simulator_fallback(self):
        client = self.seeded(1)
        client.records["room-b"][-1][1]["noise_db"] = 12.3
        self.assertEqual(self.read(client)["cards"][1]["measurement"], 12.3)

    def test_full_day_history_bound_and_empty_series(self):
        client = self.seeded(1)
        original = client.history
        def bounded(model, connection, parameter, start, end):
            self.assertEqual(end - start, 86400000)
            return original(model, connection, parameter, start, end)
        with patch.object(client, "history", side_effect=bounded):
            self.assertTrue(all(c["quality"] == "CURRENT_READBACK" for c in self.read(client, minutes=1440)["cards"]))
        self.assertEqual(self.read(MemoryClient())["cards"][0]["quality"], "NO_DATA")

    def test_empty_status_is_not_evaluated_and_legacy_status_is_not_relabelled(self):
        client = self.seeded(1)
        del client.assets["room-a"]["z:status"]
        data = self.read(client)
        self.assertIsNone(data["cards"][0]["stored_status"])
        self.assertEqual(data["cards"][0]["quality"], "NOT_EVALUATED")
        client.assets["room-a"]["z:status"] = "AVAILABLE"
        with self.assertRaises(TutorialError):
            self.read(client)

    def test_stale_and_inconsistent_results_visible(self):
        client = self.seeded()
        stale = snapshot(client, client.config, now_ms=int(client.clock.time() * 1000) + 301000)
        self.assertEqual(stale["high_labs"], [])
        self.assertEqual(stale["cards"][0]["quality"], "STALE")
        client.records["room-b"][-1][1]["noise_db"] = 99
        bad = self.read(client)["cards"][1]
        self.assertEqual(bad["quality"], "UNVERIFIED_STATUS")
        self.assertIsNone(bad["successive_high_readings"])

    def test_three_high_readings_recovery_and_normal_room(self):
        client = self.seeded(4)
        a, b = self.read(client)["cards"]
        self.assertEqual((a["stored_status"], a["successive_high_readings"]), ("High", 3))
        self.assertEqual((b["stored_status"], b["successive_high_readings"]), ("Normal", 0))
        rows = [r for r in self.read(client)["trends"] if r["room"] == a["room"] and r["comparison"] == "Above current target"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["ingested_utc"] for r in rows}), 3)
        recovered = self.read(self.seeded(8))
        self.assertEqual(recovered["high_labs"], [])
        self.assertEqual([c["stored_status"] for c in recovered["cards"]], ["Normal", "Normal"])

    def test_real_gap_is_visible_and_count_breaks_without_fabricated_rows(self):
        client = self.seeded(4)
        # A gap beyond the documented review threshold, not an invented missing round.
        stamp, payload = client.records["room-a"][-1]
        client.clock.value += 240
        client.records["room-a"][-1] = (stamp + 240000, payload)
        data = self.read(client)
        rows = [r for r in data["trends"] if r["room"] == "Computer Lab A 109"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["quality"], "GAP_REVIEW")
        self.assertEqual(data["cards"][0]["successive_high_readings"], 1)
        self.assertTrue(all(r["ingested_utc"] for r in rows))

    def render_data(self, steps=1):
        from datetime import datetime, timezone, timedelta
        data = self.read(self.seeded(steps))
        newest = max(datetime.fromisoformat(c["ingested_utc"]) for c in data["cards"])
        delta = datetime.now(timezone.utc) - newest - timedelta(seconds=2)
        for row in data["cards"] + data["trends"]:
            row["ingested_utc"] = (datetime.fromisoformat(row["ingested_utc"]) + delta).isoformat()
        return data

    def test_names_come_from_tandem_not_local_display_labels(self):
        client = self.seeded(1)
        client.config["sensors"][0]["label"] = "Local alias"
        self.assertEqual(self.read(client)["cards"][0]["room"], "Computer Lab A 109")

    def test_render_all_reference_states_and_safe_failure(self):
        from streamlit.testing.v1 import AppTest
        from datetime import datetime, timezone, timedelta
        from monitoring.presentation import card_state, noise_chart, chart_domain
        for steps in (1, 2, 4, 8):
            data = self.render_data(steps)
            with patch("monitoring.config.load", return_value=MemoryClient().config), patch("monitoring.api.TandemClient", return_value=MemoryClient()), patch("monitoring.dashboard.snapshot", return_value=data):
                app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.button[0].label, "Refresh")
            self.assertEqual(len(app.dataframe), 1)
            self.assertFalse(app.expander[0].proto.expanded)
            self.assertFalse(app.expander[1].proto.expanded)
            self.assertEqual(app.dataframe[0].value.columns.tolist(), ["Lab", "Recorded at", "Noise level (dB)", "Current target (dB)", "Compared with target", "Note"])
            html = " ".join(x.value for x in app.markdown)
            self.assertIn("Computer Lab A · 109", html)
            self.assertIn("High" if steps in (2, 4) else "Normal", html)
            spec = noise_chart(data, data["cards"][0], "America/New_York", chart_domain(data)).to_dict()
            self.assertEqual(spec["layer"][0]["encoding"]["x"]["type"], "temporal")
            self.assertEqual(spec["layer"][2]["mark"]["strokeDash"], [5, 4])
        now = datetime.now(timezone.utc)
        c = self.render_data()["cards"][0]
        c["stored_status"] = None
        self.assertEqual(card_state(c, now)[0], "Awaiting evaluation")
        c["stored_status"], c["quality"] = "High", "UNVERIFIED_STATUS"
        self.assertEqual(card_state(c, now)[0], "Status needs checking")
        c["ingested_utc"] = (now - timedelta(minutes=6)).isoformat()
        self.assertEqual(card_state(c, now)[0], "No recent reading")

    def test_refresh_range_and_unrelated_reruns(self):
        from streamlit.testing.v1 import AppTest
        data = self.render_data()
        with patch("monitoring.config.load", return_value=MemoryClient().config), patch("monitoring.api.TandemClient", return_value=MemoryClient()), patch("monitoring.dashboard.snapshot", return_value=data) as read:
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertEqual(read.call_count, 1)
            app.run()
            self.assertEqual(read.call_count, 1)
            app.button[0].click().run()
            self.assertEqual(read.call_count, 2)
            app.selectbox[0].select("24 hours").run()
            self.assertEqual(read.call_count, 3)
            self.assertEqual(read.call_args.args[2], 1440)
            read.side_effect = TutorialError("secret-marker")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertIn("Couldn't refresh", app.error[0].value)
            self.assertNotIn("secret-marker", app.error[0].value)
            self.assertEqual(len(app.dataframe), 0)

    def test_empty_history_partial_history_and_gaps(self):
        from streamlit.testing.v1 import AppTest
        from monitoring.presentation import noise_chart, chart_domain
        client = MemoryClient()
        data = self.read(client)
        self.assertEqual([c["quality"] for c in data["cards"]], ["NO_DATA", "NO_DATA"])
        with patch("monitoring.config.load", return_value=client.config), patch("monitoring.api.TandemClient", return_value=client), patch("monitoring.dashboard.snapshot", return_value=data):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Choose a longer history range" in x.value for x in app.info))
        client = self.seeded(1)
        client.records["room-a"].clear()
        data = self.read(client)
        self.assertEqual(data["cards"][0]["quality"], "NO_DATA")
        self.assertEqual(data["cards"][1]["measurement"], 40.0)
        data = self.render_data(4)
        data["trends"][2]["quality"] = "GAP_REVIEW"
        spec = noise_chart(data, data["cards"][0], "America/New_York", chart_domain(data)).to_dict()
        values = list(spec["datasets"].values())[0]
        self.assertGreater(len({r["segment"] for r in values}), 1)

    def test_timezone_dst_and_scale(self):
        from monitoring.presentation import clock_label, local_time, chart_domain
        self.assertEqual(clock_label("2026-11-16T20:24:43+00:00"), "3:24 PM")
        self.assertEqual(local_time("2026-07-16T20:24:43+00:00").utcoffset().total_seconds(), -14400)
        self.assertEqual(local_time("2026-11-16T20:24:43+00:00").utcoffset().total_seconds(), -18000)
        data = self.render_data(4)
        low, high = chart_domain(data)
        self.assertLess(low, 50)
        self.assertGreater(high, 66.5)

    def test_special_card_states_render(self):
        from streamlit.testing.v1 import AppTest
        from datetime import datetime, timezone, timedelta
        for state in ("empty", "mismatch", "old"):
            data = self.render_data()
            c = data["cards"][0]
            if state == "empty":
                c.update(stored_status=None, quality="NOT_EVALUATED")
                expected = "Awaiting evaluation"
            elif state == "mismatch":
                c.update(stored_status="High", quality="UNVERIFIED_STATUS")
                expected = "Status needs checking"
            else:
                c.update(ingested_utc=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat(), quality="STALE")
                expected = "No recent reading"
            with patch("monitoring.config.load", return_value=MemoryClient().config), patch("monitoring.api.TandemClient", return_value=MemoryClient()), patch("monitoring.dashboard.snapshot", return_value=data):
                app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertFalse(app.exception)
            self.assertIn(expected, " ".join(x.value for x in app.markdown))
