"""Small bounded APS/Tandem client, adapted from the MIT streaming tutorial.

Only protocol facts were consulted in Autodesk examples; no upstream SDK is vendored.
Every write is attempted once. Exceptions never include URLs, bodies, or credentials.
"""

import base64
import binascii
import json
import time
from urllib.parse import quote

import requests

from .config import TutorialError, credentials, key, number, urn

BASE = "https://developer.api.autodesk.com"


class ApiError(TutorialError):
    """Safe API diagnostic."""

    def __init__(self, message, http_status=None):
        super().__init__(message)
        self.http_status = http_status


class TandemClient:
    def __init__(self, region="US", write=False, session=None):
        self.session = session or requests.Session()
        # Disable implicit .netrc credentials; credentials are supplied explicitly.
        self.session.trust_env = False
        self.region, self.write = region, write
        self.token, self.expires = None, 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    def _json(self, method, url, label, expect_json=True, **kwargs):
        try:
            with self.session.request(method, url, timeout=(10, 30), allow_redirects=False,
                                      stream=True, **kwargs) as response:
                if not 200 <= response.status_code < 300:
                    raise ApiError(f"{label}: HTTP {response.status_code}; request stopped, no automatic retry.", http_status=response.status_code)
                if not expect_json:
                    return response.status_code  # Ingestion may have an empty successful body.
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ApiError(f"{label}: response exceeds tutorial's 2 MB limit; narrow the query.")
                return json.loads(content)
        except ApiError:
            raise
        except (requests.RequestException, ValueError, UnicodeError):
            raise ApiError(f"{label}: network failure or invalid JSON; delivery may be unknown after a write. No retry.") from None

    def _token(self):
        if self.token and time.monotonic() < self.expires:
            return self.token
        values = credentials(prefer_file=True)
        data = self._json("POST", BASE + "/authentication/v2/token", "APS authentication",
                          auth=(values["APS_CLIENT_ID"], values["APS_CLIENT_SECRET"]),
                          data={"grant_type": "client_credentials",
                                "scope": "data:read data:write" if self.write else "data:read"})
        if not isinstance(data, dict) or not isinstance(data.get("access_token"), str) or not data["access_token"]:
            raise ApiError("APS authentication: missing access token.")
        lifetime = number(data.get("expires_in"), "token lifetime")
        if lifetime <= 0:
            raise ApiError("APS authentication: invalid token lifetime.")
        self.token = data["access_token"]
        self.expires = time.monotonic() + max(0, lifetime - 60)
        return self.token

    def request(self, method, path, **kwargs):
        if path.endswith("/mutate") and not self.write:
            raise ApiError("This client has read-only scope.")
        return self._json(method, BASE + "/tandem/v1/" + path, "Tandem API",
                          headers={"Authorization": "Bearer " + self._token(), "Region": self.region}, **kwargs)

    def facility(self, facility_urn):
        urn(facility_urn, "dtt")
        result = self.request("GET", "twins/" + quote(facility_urn, safe=""))
        if (not isinstance(result, dict) or not isinstance(result.get("links"), list)
                or not 1 <= len(result["links"]) <= 30
                or any(not isinstance(link, dict) or not isinstance(link.get("modelId"), str) for link in result["links"])):
            raise ApiError("Unexpected or oversized facility links response.")
        models = [urn(link["modelId"], "dtm") for link in result["links"]]
        self.access_level = result.get("accessLevel", "Unknown")
        default = facility_urn.replace("urn:adsk.dtt:", "urn:adsk.dtm:", 1)
        if default not in models or len(set(models)) != len(models):
            raise ApiError("Facility default model missing or duplicate model links.")
        return default, models

    def schema(self, model):
        result = self.request("GET", f"modeldata/{quote(model, safe='')}/schema")
        if not isinstance(result, dict) or not isinstance(result.get("attributes"), list):
            raise ApiError("Unexpected model schema response.")
        attrs = {}
        for item in result["attributes"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in attrs:
                raise ApiError("Invalid or duplicate schema attribute.")
            attrs[item["id"]] = item
        return attrs

    def scan(self, model, keys=None, columns=None):
        body = {"includeHistory": False, "skipArrays": True}
        if keys:
            body["keys"] = [key(k) for k in keys]
        if columns:
            body["qualifiedColumns"] = columns
        else:
            body["families"] = ["n", "z", "x"]
        data = self.request("POST", f"modeldata/{quote(model, safe='')}/scan", json=body)
        # Autodesk scans have a version sentinel, then flat property dictionaries.
        if not isinstance(data, list) or not data or data[0] != "v1" or len(data) > 10001:
            raise ApiError("Unexpected scan version/shape or too many rows; narrow the query.")
        rows, seen = [], set()
        for row in data[1:]:
            if not isinstance(row, dict):
                raise ApiError("Unexpected scan row.")
            short = key(row.get("k"))
            if short in seen:
                raise ApiError("Duplicate scan key.")
            seen.add(short)
            rows.append({**row, "k": short})
        if keys and seen != {key(k) for k in keys}:
            raise ApiError("Configured elements are missing or scan returned unintended elements.")
        return rows

    def stream_configs(self, model):
        data = self.request("GET", f"models/{quote(model, safe='')}/stream-configs")
        if not isinstance(data, list):
            raise ApiError("Unexpected stream configuration response.")
        mappings = {}
        for row in data:
            if not isinstance(row, dict):
                raise ApiError("Unexpected stream configuration entry.")
            stream = key(row.get("elementId"), logical=True)
            settings = row.get("streamSettings")
            if settings is None:
                settings = {}
            if not isinstance(settings, dict):
                raise ApiError("Invalid stream settings.")
            source = settings.get("sourceMapping")
            if source is None:
                source = {}
            if not isinstance(source, dict) or stream in mappings:
                raise ApiError("Invalid or duplicate stream mappings.")
            # Expose only parameter -> flat field, never raw integration settings.
            mappings[stream] = {}
            for pid, item in source.items():
                if not isinstance(pid, str) or not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    raise ApiError("Malformed stream source mapping.")
                path = item["path"]
                if path.startswith("$."):
                    path = path[2:]
                elif ((path.startswith("$['") and path.endswith("']"))
                      or (path.startswith('$["') and path.endswith('"]'))):
                    path = path[3:-2]
                if not path or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in path):
                    path = None
                mappings[stream][pid] = path
        return mappings

    def history(self, model, connection, parameter, start_ms, end_ms, page_size=1000):
        """Adapted day-aware pagination, half-open UTC bounds, with a hard page cap.

        Do not stop on short pages: storage may cap pages below the requested size.
        Empty UTC days must not hide later days. Preserve millisecond timestamps.
        """
        if not 2 <= page_size <= 1000 or not 0 <= start_ms < end_ms or end_ms - start_ms > 86400000:
            raise TutorialError("History bounds must increase and span at most 24 real hours; page size 2..1000.")
        path = f"timeseries/models/{quote(model, safe='')}/streams/{quote(key(connection, logical=True), safe='')}"
        result, pages, window_start = {}, 0, start_ms
        day = 86400000
        while window_start < end_ms:
            window_end = min(end_ms, (window_start // day + 1) * day)
            cursor = window_start - 1
            while cursor < window_end:
                pages += 1
                if pages > 100:
                    raise ApiError("History page limit reached; narrow the real-time range.")
                data = self.request("GET", path, params={"from": cursor, "to": window_end,
                                    "substream": parameter, "limit": page_size, "sort": "asc"})
                if not isinstance(data, dict) or set(data) - {parameter}:
                    raise ApiError("Unexpected history parameter response.")
                values = data.get(parameter, {})
                if not isinstance(values, dict) or len(values) > page_size:
                    raise ApiError("Unexpected history values or page size.")
                page = {}
                for timestamp, value in values.items():
                    try:
                        stamp = int(timestamp)
                    except (ValueError, TypeError):
                        raise ApiError("Invalid history timestamp.") from None
                    if str(stamp) != str(timestamp) or not cursor <= stamp <= window_end:
                        raise ApiError("History returned timestamps outside query bounds.")
                    number(value, "API measurement")
                    page[stamp] = value
                    if window_start <= stamp < window_end:
                        if stamp in result and result[stamp] != value:
                            raise ApiError("History changed while paging; read after ingestion stops.")
                        result[stamp] = value
                if not page and cursor == window_start - 1:
                    cursor = window_start
                    continue
                if not page:
                    break
                next_cursor = max(page) + (1 if cursor in page else 0)
                if next_cursor <= cursor:
                    raise ApiError("History pagination made no progress.")
                cursor = next_cursor
            window_start = window_end
        return sorted(result.items())

    def ingest(self, target, payload):
        endpoint, auth = target
        return self._json("POST", endpoint, "Individual ingestion", expect_json=False, auth=auth, json=payload)

    def mutate(self, model, changes):
        """changes = [(short element key, qualified property ID, typed value), ...]."""
        if not changes:
            return None
        if len(changes) > 40:
            raise TutorialError("Mutation exceeds tutorial limit.")
        body = {"keys": [], "muts": [], "desc": "Community monitoring tutorial: reference rule"}
        for element, parameter, value in changes:
            family, column = parameter.split(":", 1)
            if family != "z" or not column:
                raise TutorialError("Only configured custom properties can be written.")
            body["keys"].append(key(element))
            body["muts"].append(["i", family, column, value])
        result = self.request("POST", f"modeldata/{quote(model, safe='')}/mutate", json=body)
        if not isinstance(result, dict) or type(result.get("timestamp")) is not int:
            raise ApiError("Mutation response lacks its real change timestamp; delivery must be checked manually.")
        return result["timestamp"]


def associations(row, kind=None):
    """Decode cross-model host/room refs (16-byte model + 24-byte element).

    Empty room override intentionally suppresses an original room relationship.
    Protocol layout is documented in Autodesk's encoding example.
    """
    result = set()
    values = {"host": (row.get("x:p"),), "room": (row.get("x:!r", row.get("x:r")),)}
    if kind not in (None, "host", "room"):
        raise ApiError("Unknown relationship kind.")
    selected = values[kind] if kind else values["host"] + values["room"]
    for value in selected:
        if value in (None, ""):
            continue
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise ApiError("Invalid host/room relationship encoding.") from None
        if len(raw) % 40:
            raise ApiError("Unexpected host/room relationship size.")
        for offset in range(0, len(raw), 40):
            model = "urn:adsk.dtm:" + base64.urlsafe_b64encode(raw[offset:offset + 16]).decode().rstrip("=")
            element = base64.urlsafe_b64encode(raw[offset + 16:offset + 40]).decode().rstrip("=")
            result.add((model, key(element)))
    return result
