"""Public simulation settings and private model mappings, never local rule targets.

Credential parser adapted from rgallopp's MIT streaming tutorial (see NOTICE.md).
"""

import base64
import binascii
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class TutorialError(ValueError):
    """Controlled, displayable diagnostics; do not put raw configuration in these."""


def number(value, label="numeric value"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TutorialError(f"Missing or invalid {label}; expected a finite number.")
    return value


def key(text, logical=False):
    """20-byte scan key <-> 24-byte full key; logical streams need logical flags.

    Assets can be physical OR logical. Never prepend stream flags to asset keys.
    Scan requests and mutation keys use the short form; stream URLs use full form.
    """
    try:
        raw = base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except (TypeError, ValueError, binascii.Error):
        raise TutorialError("Invalid element/connection key encoding.") from None
    if len(raw) == 24:
        if logical and raw[:4] != b"\x01\x00\x00\x00":
            raise TutorialError("Connection full key must have logical flags.")
        raw = raw[4:]
    if len(raw) != 20:
        raise TutorialError("Expected a 20-byte short or 24-byte full element key.")
    if logical:
        raw = b"\x01\x00\x00\x00" + raw
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def urn(value, kind):
    if not isinstance(value, str) or not re.fullmatch(r"urn:adsk\." + kind + r":[A-Za-z0-9_-]+", value):
        raise TutorialError(f"Fill a valid {kind} URN from Tandem.")
    return value


def parameter(value):
    if not isinstance(value, str) or not re.fullmatch(r"z:[A-Za-z0-9_-]+", value):
        raise TutorialError("Fill a custom qualified parameter ID from schema (z:column).")
    return value


def read_json(path):
    try:
        with Path(path).open(encoding="utf-8-sig") as source:
            return json.load(source, parse_constant=lambda _: None)
    except (OSError, UnicodeError, ValueError):
        raise TutorialError("Cannot read JSON; check file access and JSON syntax.") from None


def db_value(value):
    """Finite dB value on the model's one-decimal scale; no physical conversion."""
    number(value, "dB value")
    if not math.isclose(value, round(value, 1), rel_tol=0, abs_tol=1e-8):
        raise TutorialError("Expected a dB value representable to one decimal place.")
    return round(float(value), 1)


def load(path, live=False):
    """Version 2: one measurement, model target and restricted status per room."""
    config = read_json(path)
    try:
        if not isinstance(config, dict) or config.get("schema_version") != 2:
            raise TutorialError("Use schema_version 2 and the current three-parameter configuration template; preserve old files first.")
        field = config["measurement_field"]
        if not isinstance(field, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", field) or field in {"time", "timestamp", "epoch", "id"}:
            raise TutorialError("Use a flat numeric measurement field distinct from reserved timestamp fields.")
        if type(config["precision"]) is not int or (config["specification"], config["unit"], config["symbol"], config["precision"]) != ("soundPressureLevel", "decibels", "dB", 1):
            raise TutorialError("This reference requires Sound Pressure Level, decibels, dB and precision 1.")
        if config.get("region") not in ("US", "EMEA", "AUS"):
            raise TutorialError("Set region to US, EMEA, or AUS.")
        number(config["max_history_gap_seconds"], "history gap setting")
        if config["max_history_gap_seconds"] < 60:
            raise TutorialError("History gap setting must be at least 60 real seconds.")
        sensors = config["sensors"]
        if not isinstance(sensors, list) or not 2 <= len(sensors) <= 10:
            raise TutorialError("Configure 2..10 distinct sensors.")
        ids, connections, assets, env_names, lengths = set(), set(), set(), set(), set()
        for sensor in sensors:
            if not re.fullmatch(r"[a-z][a-z0-9-]*", sensor["id"]) or sensor["id"] in ids:
                raise TutorialError("Use distinct lowercase sensor IDs.")
            ids.add(sensor["id"])
            for name in ("label", "expected_connection_name", "ingestion_env"):
                if not isinstance(sensor[name], str) or not sensor[name].strip():
                    raise TutorialError("Each sensor needs a label, exact connection name and credential name.")
            values = sensor["simulation"]["values"]
            if not isinstance(values, list) or not 1 <= len(values) <= 256:
                raise TutorialError("Give each sensor a bounded numbered-round value sequence.")
            for value in values:
                db_value(value)
            lengths.add(len(values))
            if not live:
                continue
            sensor["connection_key"] = key(sensor["connection_key"], logical=True)
            if sensor["connection_key"] in connections:
                raise TutorialError("Each sensor needs a separate connection.")
            connections.add(sensor["connection_key"])
            env_name = sensor["ingestion_env"]
            if not re.fullmatch(r"TANDEM_[A-Z0-9_]+_URL", env_name) or env_name in env_names:
                raise TutorialError("Use distinct TANDEM_*_URL credential names.")
            env_names.add(env_name)
            if set(sensor["parameters"]) != {field}:
                raise TutorialError("Map only the configured measurement field to Noise Level.")
            parameter(sensor["parameters"][field])
            asset = sensor["asset"]
            urn(asset["model_urn"], "dtm")
            asset["element_key"] = key(asset["element_key"])
            address = (asset["model_urn"], asset["element_key"])
            if address in assets:
                raise TutorialError("Select different room/equipment instances.")
            assets.add(address)
            if parameter(asset["target_parameter"]) == parameter(asset["status_parameter"]):
                raise TutorialError("Target and status need different schema IDs.")
            for name in ("number_parameter", "comments_parameter"):
                if not re.fullmatch(r"[rnz]:[A-Za-z0-9_!-]+", asset[name]):
                    raise TutorialError("Fill room number and Comments IDs from the owning model schema.")
            for name in ("expected_name", "expected_number", "comments_contains"):
                if not isinstance(asset[name], str) or not asset[name]:
                    raise TutorialError("Configure exact room identity and expected Revit Comments.")
        if len(lengths) != 1:
            raise TutorialError("Sensors must define the same number of rounds.")
        if live:
            urn(config["facility_urn"], "dtt")
    except (KeyError, TypeError, AttributeError):
        raise TutorialError("Missing or malformed configuration; compare the current public template.") from None
    return config


def credentials(path=None, names=("APS_CLIENT_ID", "APS_CLIENT_SECRET"), prefer_file=False):
    """Literal .env, without interpolation or process mutation.

    API/sender callers explicitly prefer this checkout's private file, preventing
    unrelated inherited APS credentials or destination URLs from taking over.
    Other callers retain the optional process-environment precedence.
    """
    path = ROOT / ".env" if path is None else Path(path)
    values = {}
    try:
        if path.exists():
            for index, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                name, separator, value = line.partition("=")
                name, value = name.strip(), value.strip()
                allowed = name in {"APS_CLIENT_ID", "APS_CLIENT_SECRET"} or re.fullmatch(r"TANDEM_[A-Z0-9_]+_URL", name)
                if not separator or not allowed or name in values:
                    raise TutorialError(f"Invalid .env assignment on line {index}.")
                if value.startswith(('"', "'")):
                    if len(value) < 2 or value[-1] != value[0]:
                        raise TutorialError(f"Invalid .env quotes on line {index}.")
                    value = value[1:-1]
                values[name] = value
    except (OSError, UnicodeError):
        raise TutorialError("Cannot read root .env as UTF-8.") from None
    result = {name: values[name] if prefer_file and name in values else os.environ.get(name, values.get(name, "")) for name in names}
    if any(not value or "REPLACE" in value for value in result.values()):
        raise TutorialError("Fill required credentials in .env or the process environment.")
    return result


def destination(url, model, connection):
    """Adapted ingestion validation; bind Copy Link destination to configured API IDs."""
    try:
        parsed = urlsplit(url.strip())
        segments = unquote(parsed.path).rstrip("/").split("/")
        if (parsed.scheme != "https" or parsed.hostname != "tandem.autodesk.com"
                or parsed.port not in (None, 443) or not parsed.password
                or parsed.query or parsed.fragment or len(segments) != 8
                or segments[:6] != ["", "api", "v1", "timeseries", "models", model]
                or segments[6] != "streams"):
            raise TutorialError("Ingestion URL must match the configured model and connection.")
        if key(segments[7], logical=True) != connection:
            raise TutorialError("Ingestion URL connection does not match configuration.")
        path = f"/api/v1/timeseries/models/{quote(model, safe=':')}/streams/{connection}"
        return "https://tandem.autodesk.com" + path, (unquote(parsed.username or ""), unquote(parsed.password))
    except (TypeError, ValueError, IndexError, AttributeError):
        raise TutorialError("Invalid Individual ingestion URL or destination mismatch.") from None
