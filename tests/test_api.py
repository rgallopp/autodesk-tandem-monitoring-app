"""Mock HTTP/protocol tests; no facility calls and no live evidence."""

import json
import unittest
from unittest.mock import Mock, patch

import requests

from monitoring.api import ApiError, BASE, TandemClient, associations
from monitoring.config import TutorialError, key
from tests.support import encoded, fixture


def response(data=None, status=200, raw=None):
    value = Mock(status_code=status)
    value.iter_content.return_value = [raw if raw is not None else json.dumps(data).encode()]
    value.__enter__ = Mock(return_value=value)
    value.__exit__ = Mock(return_value=False)
    return value


class ApiTests(unittest.TestCase):
    def client(self, replies=(), write=False):
        session = Mock()
        session.request.side_effect = replies
        return TandemClient(session=session, write=write), session

    def test_auth_scope_cache_headers_region_timeout_and_no_redirects(self):
        for writing in (False, True):
            client, session = self.client([response({"access_token": "fixture-token", "expires_in": 3600}), response({}), response({})], write=writing)
            client.region = "EMEA"
            with patch("monitoring.api.credentials", return_value={"APS_CLIENT_ID": "fixture-id", "APS_CLIENT_SECRET": "fixture-secret"}):
                client.request("GET", "example")
                client.request("GET", "example")
            calls = session.request.call_args_list
            self.assertEqual(len(calls), 3)
            self.assertEqual(calls[0].kwargs["auth"], ("fixture-id", "fixture-secret"))
            self.assertEqual(calls[0].kwargs["data"]["scope"], "data:read data:write" if writing else "data:read")
            self.assertEqual(calls[1].kwargs["headers"], {"Authorization": "Bearer fixture-token", "Region": "EMEA"})
            self.assertEqual(calls[1].kwargs["timeout"], (10, 30))
            self.assertFalse(calls[1].kwargs["allow_redirects"])
            self.assertFalse(session.trust_env)

    def test_http_failures_timeout_malformed_json_size_limit_sanitized_once(self):
        for reply in [response(status=302), response(status=401), response(status=429), response(status=500),
                      requests.Timeout("private-marker"), response(raw=b"private-marker"),
                      response(raw=b"x" * 2_000_001)]:
            client, session = self.client([reply])
            with self.assertRaises(ApiError) as caught:
                client._json("POST", BASE, "Test request", json={"secret": "private-marker"})
            self.assertNotIn("private-marker", str(caught.exception))
            self.assertEqual(session.request.call_count, 1)
        client, session = self.client([response(status=503)])
        with self.assertRaisesRegex(ApiError, "HTTP 503"):
            client._json("GET", BASE, "Test")

    def test_successful_empty_ingestion_body_and_auth_separated(self):
        client, session = self.client([response(status=204, raw=b"")])
        payload = {"noise_db": 45.0}
        self.assertEqual(client.ingest(("https://tandem.autodesk.com/fixture", ("", "fixture-secret")), payload), 204)
        self.assertEqual(session.request.call_args.kwargs["json"], payload)
        self.assertEqual(session.request.call_args.kwargs["auth"], ("", "fixture-secret"))
        self.assertNotIn("fixture-secret", session.request.call_args.args[1])

    def test_scan_version_arrays_missing_duplicate_and_short_keys(self):
        client, _ = self.client()
        connection = fixture()["sensors"][0]["connection_key"]
        short = key(connection)
        with patch.object(client, "request", return_value=["v1", {"k": short, "z:target": 55}]) as request:
            rows = client.scan("urn:adsk.dtm:fixture", [connection], ["z:target"])
        self.assertEqual(rows, [{"k": short, "z:target": 55}])
        self.assertEqual(request.call_args.kwargs["json"], {"keys": [short], "qualifiedColumns": ["z:target"], "includeHistory": False, "skipArrays": True})
        for data in [[], {}, ["v2"], ["v1", None], ["v1"], ["v1", {"k": short}, {"k": short}]]:
            with patch.object(client, "request", return_value=data), self.assertRaises(TutorialError):
                client.scan("urn:adsk.dtm:fixture", [connection])

    def test_schema_and_mapping_validation_and_redaction(self):
        client, _ = self.client()
        stream = fixture()["sensors"][0]["connection_key"]
        data = [{"elementId": key(stream), "privateIntegration": "private-marker", "streamSettings": {
            "sourceMapping": {"z:noise": {"path": "$.noise_db"}}}}]
        with patch.object(client, "request", return_value=data):
            saved = client.stream_configs("urn:adsk.dtm:fixture")
        self.assertEqual(saved[stream], {"z:noise": "noise_db"})
        self.assertNotIn("private-marker", json.dumps(saved))
        for invalid in [{}, [{"elementId": stream, "streamSettings": []}], data + data]:
            with patch.object(client, "request", return_value=invalid), self.assertRaises(TutorialError):
                client.stream_configs("urn:adsk.dtm:fixture")
        with patch.object(client, "request", return_value={"attributes": [{"id": "z:1"}, {"id": "z:1"}]}), self.assertRaises(ApiError):
            client.schema("urn:adsk.dtm:fixture")

    def test_source_path_mixed_quotes_do_not_validate_as_a_flat_field(self):
        client, _ = self.client()
        stream = fixture()["sensors"][0]["connection_key"]
        malformed = "$['noise_db\"]"
        data = [{"elementId": stream, "streamSettings": {"sourceMapping": {"z:noise": {"path": malformed}}}}]
        with patch.object(client, "request", return_value=data):
            self.assertIsNone(client.stream_configs("urn:adsk.dtm:fixture")[stream]["z:noise"])

    def test_mutation_repeats_keys_uses_typed_values_and_owning_model(self):
        client, _ = self.client(write=True)
        asset = fixture()["sensors"][0]["asset"]
        changes = [(asset["element_key"], "z:status", "High")]
        with patch.object(client, "request", return_value={"timestamp": 12345}) as request:
            self.assertEqual(client.mutate(asset["model_urn"], changes), 12345)
        body = request.call_args.kwargs["json"]
        self.assertEqual(body["keys"], [asset["element_key"]])
        self.assertEqual(body["muts"], [["i", "z", "status", "High"]])
        self.assertIn("urn%3Aadsk.dtm%3A", request.call_args.args[1])
        with patch.object(client, "request", return_value={}), self.assertRaises(ApiError):
            client.mutate(asset["model_urn"], changes)
        readonly, _ = self.client()
        with self.assertRaises(ApiError):
            readonly.mutate(asset["model_urn"], changes)
        with patch.object(client, "request") as request:
            self.assertIsNone(client.mutate(asset["model_urn"], []))
            request.assert_not_called()

    def test_relationships_cross_model_room_override_and_host(self):
        c = fixture()
        asset = c["sensors"][0]["asset"]
        import base64
        raw = b"m" * 16 + b"\0" * 4 + base64.urlsafe_b64decode(asset["element_key"] + "=")
        ref = encoded(raw)
        address = (asset["model_urn"], asset["element_key"])
        self.assertIn(address, associations({"x:r": ref}))
        self.assertNotIn(address, associations({"x:r": ref, "x:!r": ""}))
        self.assertIn(address, associations({"x:p": ref}))
        for bad in ["bad!", encoded(b"x"), [], 5]:
            with self.assertRaises(ApiError):
                associations({"x:r": bad})

    def test_history_inclusive_exclusive_short_pages_midnight_and_empty_day(self):
        day = 86400000
        # At most 24h total, but straddles UTC midnight; storage windows are separate.
        points = {day - 2000: 1, day - 1: 2, day: 3, day + 1: 4, day + 2000: 5}
        connection = fixture()["sensors"][0]["connection_key"]
        for inclusive in (False, True):
            client, _ = self.client()
            def query(method, path, params):
                cursor = params["from"]
                if inclusive and cursor == day - 1:
                    return {"z:noise": {}}  # Previous storage day exhausted at look-behind.
                subset = [(stamp, value) for stamp, value in points.items() if (stamp >= cursor if inclusive else stamp > cursor)
                          and stamp <= params["to"] and stamp // day == (cursor + 1) // day]
                return {"z:noise": {str(stamp): value for stamp, value in subset[:1]}}
            # Separate simple inclusive API without day-bucket quirk verifies every ms.
            def flat_query(method, path, params):
                subset = [(stamp, value) for stamp, value in points.items() if
                          (stamp >= params["from"] if inclusive else stamp > params["from"]) and stamp <= params["to"]]
                return {"z:noise": {str(stamp): value for stamp, value in subset[:1]}}
            with patch.object(client, "request", side_effect=flat_query):
                self.assertEqual(client.history("urn:adsk.dtm:fixture", connection, "z:noise", day - 3000, day + 2000, 2), list(points.items())[:-1])
            with patch.object(client, "request", side_effect=query):
                self.assertEqual(client.history("urn:adsk.dtm:fixture", connection, "z:noise", day - 3000, day + 2000, 2), list(points.items())[:-1])
            sparse = {day + 1500: 42}
            def sparse_query(method, path, params):
                cursor = params["from"]
                values = [(stamp, value) for stamp, value in sparse.items() if stamp // day == (cursor + 1) // day
                          and (stamp >= cursor if inclusive else stamp > cursor) and stamp <= params["to"]]
                return {"z:noise": {str(k): v for k, v in values[:1]}}
            with patch.object(client, "request", side_effect=sparse_query):
                self.assertEqual(client.history("urn:adsk.dtm:fixture", connection, "z:noise", day - 3000, day + 2000, 2), [(day + 1500, 42)])

    def test_history_invalid_data_changed_overlap_and_page_cap(self):
        client, _ = self.client()
        connection = fixture()["sensors"][0]["connection_key"]
        for bad in [{"unexpected": {}}, {"z:n": []}, {"z:n": {"1500": float("nan")}}, {"z:n": {"3000": 5}}, {"z:n": {"bad": 5}}]:
            with patch.object(client, "request", return_value=bad), self.assertRaises(TutorialError):
                client.history("urn:adsk.dtm:fixture", connection, "z:n", 1000, 2000)
        with patch.object(client, "request", side_effect=[{"z:n": {"1000": 1}}, {"z:n": {"1000": 2}}]), self.assertRaises(ApiError):
            client.history("urn:adsk.dtm:fixture", connection, "z:n", 1000, 2000)
        def endless(method, path, params):
            return {"z:n": {str(params["from"] + 1): 1}}
        with patch.object(client, "request", side_effect=endless) as request, self.assertRaisesRegex(ApiError, "page limit"):
            client.history("urn:adsk.dtm:fixture", connection, "z:n", 1000, 10000)
        self.assertEqual(request.call_count, 100)
