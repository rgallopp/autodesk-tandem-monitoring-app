"""Offline configuration, numeric dB, restricted Text, routing and preview checks."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from monitoring import config
from monitoring.__main__ import main, discover
from monitoring.rules import evaluate, decode_status, status_definition
from monitoring.simulation import rounds
from tests.support import fixture, environment, MemoryClient


class CoreTests(unittest.TestCase):
    def load_case(self, value, live=True):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return config.load(path, live=live)

    def test_template_preview_and_live_placeholders(self):
        example = config.load(config.ROOT / "config/project.example.json")
        self.assertEqual(len(example["sensors"]), 2)
        with self.assertRaises(config.TutorialError):
            self.load_case(example)
        self.assertEqual(self.load_case(fixture()), fixture())

    def test_bad_config_and_duplicate_identities(self):
        for mutate in [lambda c: c.update(schema_version=1), lambda c: c.update(precision=2), lambda c: c.update(precision=True),
                       lambda c: c.update(unit="unitless"), lambda c: c.update(measurement_field="timestamp"),
                       lambda c: c["sensors"].pop(),
                       lambda c: c["sensors"][1].update(connection_key=c["sensors"][0]["connection_key"]),
                       lambda c: c["sensors"][0]["parameters"].update(extra="z:extra"),
                       lambda c: c["sensors"][0]["simulation"].update(values=[float("nan")]),
                       lambda c: c["sensors"][0]["simulation"].update(values=[45.12]),
                       lambda c: c["sensors"][1].update(ingestion_env=c["sensors"][0]["ingestion_env"])]:
            value = fixture()
            mutate(value)
            with self.assertRaises(config.TutorialError):
                self.load_case(value)

    def test_literal_credentials_and_explicit_project_file_precedence(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder) / ".env"
            path.write_text('APS_CLIENT_ID="fixture-id"\nAPS_CLIENT_SECRET=fixture#literal=value\n', encoding="utf-8")
            self.assertEqual(config.credentials(path)["APS_CLIENT_SECRET"], "fixture#literal=value")
            self.assertNotIn("APS_CLIENT_ID", os.environ)
            with patch.dict(os.environ, {"APS_CLIENT_ID": "unrelated-process-id"}):
                self.assertEqual(config.credentials(path)["APS_CLIENT_ID"], "unrelated-process-id")
                self.assertEqual(config.credentials(path, prefer_file=True)["APS_CLIENT_ID"], "fixture-id")
            path.write_text('UNKNOWN=private-marker', encoding="utf-8")
            with self.assertRaises(config.TutorialError) as caught:
                config.credentials(path)
            self.assertNotIn("private-marker", str(caught.exception))

    def test_destination_identity_and_secret_redaction(self):
        c = fixture()
        s = c["sensors"][0]
        model = c["facility_urn"].replace("dtt:", "dtm:")
        url = environment(c)[s["ingestion_env"]]
        endpoint, auth = config.destination(url, model, s["connection_key"])
        self.assertNotIn("fixture-secret", endpoint)
        self.assertEqual(auth, ("", "fixture-secret"))
        for bad in [url.replace("https:", "http:"), url.replace("tandem.autodesk.com", "example.invalid"),
                    url + "?private-marker", url.replace(model, "urn:adsk.dtm:wrong"),
                    url.replace(s["connection_key"], c["sensors"][1]["connection_key"])]:
            with self.assertRaises(config.TutorialError) as caught:
                config.destination(bad, model, s["connection_key"])
            self.assertNotIn("private-marker", str(caught.exception))

    def test_numbered_sequence_and_timestamp_free_exact_samples(self):
        c = fixture()
        data = rounds(c)
        self.assertEqual(data[0], {"room-a": {"noise_db": 45.0}, "room-b": {"noise_db": 40.0}})
        self.assertEqual(rounds(c, 2, 7), data[1:])
        self.assertEqual(data, rounds(c))
        self.assertTrue(all(set(p) == {"noise_db"} for batch in data for p in batch.values()))
        for start, steps in [(0, 1), (1, 0), (8, 2), (True, 1)]:
            with self.assertRaises(config.TutorialError):
                rounds(c, start, steps)

    def test_db_equality_initialization_high_repetition_and_recovery(self):
        self.assertEqual(evaluate(55.0, 55.0), "Normal")
        self.assertEqual(evaluate(55.1, 55), "High")
        c = fixture()
        results = [evaluate(b["room-a"]["noise_db"], 55) for b in rounds(c)]
        self.assertEqual(results, ["Normal", "High", "High", "High", "Normal", "Normal", "Normal", "Normal"])
        self.assertTrue(all(evaluate(b["room-b"]["noise_db"], 50) == "Normal" for b in rounds(c)))
        for value in [True, None, "45", float("inf"), 45.12]:
            with self.assertRaises(config.TutorialError):
                config.db_value(value)

    def test_restricted_status_exact_labels_and_schema_encoded_readback(self):
        attr = MemoryClient().schema("fixture")["z:status"]
        self.assertEqual(decode_status(None, attr), None)
        self.assertEqual(decode_status("", attr), None)
        self.assertEqual(decode_status("High", attr), "High")
        self.assertEqual(decode_status(1, attr), "Normal")
        self.assertEqual(decode_status("2", attr), "High")
        for value in ["high", "Unknown", 0, True]:
            with self.assertRaises(config.TutorialError):
                decode_status(value, attr)
        attr["allowedValues"]["list"] = ["Normal", "high"]
        with self.assertRaises(config.TutorialError):
            status_definition(attr)

    def test_preview_offline_and_writes_require_send(self):
        with patch("monitoring.__main__.TandemClient") as client, contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["preview", "--steps", "1"]), 0)
            self.assertEqual(main(["seed"]), 1)
            self.assertEqual(main(["pilot"]), 1)
        client.assert_not_called()
        self.assertIn('"noise_db": 45.0', out.getvalue())

    def test_discovery_keeps_candidates_and_ambiguities(self):
        client = MemoryClient()
        original = client.scan
        def scan(*args):
            rows = original(*args)
            for row in rows:
                row["n:n"] = "Duplicate"
            return rows
        with patch.object(client, "scan", side_effect=scan):
            data = discover(client, client.config["facility_urn"])
        self.assertEqual(len(data["elements"]), 2)
        self.assertEqual(data["ambiguities"][0]["kind"], "element_name")

    def test_generated_reference_table_matches_actual_rule(self):
        from scripts.reference_expectations import expected_rows, render_table
        rows = expected_rows()
        self.assertEqual(len(rows), 16)
        self.assertEqual([r["status"] for r in rows if r["room"] == "Computer Lab A 109"],
                         ["Normal", "High", "High", "High", "Normal", "Normal", "Normal", "Normal"])
        self.assertIn(render_table(), (config.ROOT / "docs/REFERENCE_PILOT.md").read_text(encoding="utf-8"))

    def test_key_forms_and_physical_vs_logical(self):
        import base64
        short = fixture()["sensors"][0]["asset"]["element_key"]
        physical = base64.urlsafe_b64encode(b"\0" * 4 + base64.urlsafe_b64decode(short + "=")).decode().rstrip("=")
        self.assertEqual(config.key(physical), short)
        self.assertEqual(config.key(config.key(short, logical=True)), short)
        with self.assertRaises(config.TutorialError):
            config.key(physical, logical=True)
        for bad in [None, "bad!", "tiny", 42]:
            with self.assertRaises(config.TutorialError):
                config.key(bad)


    def test_empty_discovery_inventory_is_visible_not_a_readiness_claim(self):
        from monitoring.__main__ import discover
        from tests.support import MemoryClient
        client = MemoryClient()
        with patch.object(client, "scan", return_value=[]):
            data = discover(client, client.config["facility_urn"])
        self.assertEqual(data["elements"], [])
        self.assertTrue(data["warnings"])
