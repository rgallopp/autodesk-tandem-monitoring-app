"""Validate lab destinations, submit readings, and write each accepted reading's status."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .api import ApiError, associations
from .config import ROOT, TutorialError, credentials, destination, key, db_value, number, read_json
from .rules import evaluate, decode_status, status_definition

MIN_SEND_INTERVAL = 60


class Interrupted(TutorialError):
    """The operator stopped the run before its next operation."""


def asset_state(client, sensor, status_attribute):
    asset = sensor["asset"]
    columns = [asset["target_parameter"], asset["status_parameter"]]
    row = client.scan(asset["model_urn"], [asset["element_key"]], columns)[0]
    return {"target": db_value(row.get(asset["target_parameter"])),
            "status": decode_status(row.get(asset["status_parameter"]), status_attribute),
            "status_attribute": status_attribute}


def preflight(client, config, mappings=True, require_write=False):
    """Verify both intended destinations before sending; target values stay in Tandem."""
    default, models = client.facility(config["facility_urn"])
    if require_write and getattr(client, "access_level", "Unknown") not in ("ReadWrite", "Manage"):
        raise TutorialError("Status writeback needs facility Edit access. In Tandem: Users > Services > select this APS app > change Read to Edit > Save. No measurement was sent.")
    needed = {default} | {s["asset"]["model_urn"] for s in config["sensors"]}
    if not needed.issubset(models):
        raise TutorialError("An owning model is outside the configured facility.")
    schemas = {model: client.schema(model) for model in sorted(needed)}
    connections = client.scan(default, [s["connection_key"] for s in config["sensors"]],
                              ["n:a", "n:n", "n:!n", "n:v", "n:!v", "x:p", "x:r", "x:!r"])
    connections = {key(row["k"], logical=True): row for row in connections}
    saved = client.stream_configs(default) if mappings else {}
    states = {}
    for sensor in config["sensors"]:
        asset = sensor["asset"]
        stream = connections[sensor["connection_key"]]
        if stream.get("n:a") != 0x01000003 or (stream.get("n:!n") or stream.get("n:n")) != sensor["expected_connection_name"]:
            raise TutorialError("A connection key does not identify the intended named Individual connection.")
        if stream.get("n:!v", stream.get("n:v")) != config["classifications"]["connection"]:
            raise TutorialError("Connection classification does not match General Measuring Instruments.")
        address = (asset["model_urn"], asset["element_key"])
        if any(address not in associations(stream, kind) for kind in ("host", "room")):
            raise TutorialError("Both Host and effective Rooms relationship must identify the configured room.")
        columns = ["n:n", "n:!n", "n:a", "n:v", "n:!v", asset["number_parameter"], asset["comments_parameter"],
                   asset["target_parameter"], asset["status_parameter"]]
        row = client.scan(asset["model_urn"], [asset["element_key"]], columns)[0]
        if (row.get("n:a") != 5 or (row.get("n:!n") or row.get("n:n")) != asset["expected_name"]
                or str(row.get(asset["number_parameter"])) != asset["expected_number"]
                or asset["comments_contains"] not in str(row.get(asset["comments_parameter"], ""))):
            raise TutorialError("Room name/number/Revit Comments do not match the selected lab.")
        if row.get("n:!v", row.get("n:v")) != config["classifications"]["room"]:
            raise TutorialError("Room classification must match Laboratory Spaces.")
        measurement = schemas[default].get(sensor["parameters"][config["measurement_field"]])
        target = schemas[asset["model_urn"]].get(asset["target_parameter"])
        status = schemas[asset["model_urn"]].get(asset["status_parameter"])
        for attr, role, types in ((measurement, "measurement", {3, 4}), (target, "target", {3, 4}), (status, "status", {20})):
            if (not isinstance(attr, dict) or attr.get("name") != config["parameter_names"][role]
                    or attr.get("dataType") not in types or str(attr.get("context", "")).lower() != "e"
                    or attr.get("fam", "z") != "z"):
                raise TutorialError("Parameter name/type/Element context/custom family does not match the three-parameter contract.")
        expected = (config["specification"], config["unit"], config["symbol"], config["precision"])
        for attr in (measurement, target):
            if tuple(attr.get(n) for n in ("forgeSpec", "forgeUnit", "forgeSymbol", "precision")) != expected:
                raise TutorialError("Noise Level and Noise Target must both be Sound Pressure Level / Decibels / dB / precision 1.")
        status_definition(status)
        if mappings and saved.get(sensor["connection_key"], {}).get(sensor["parameters"][config["measurement_field"]]) != config["measurement_field"]:
            raise TutorialError("Noise mapping is not saved. Map noise_db to Noise Level on BOTH new connections; leave timestamp mapping unset.")
        states[sensor["id"]] = {"room_name": row.get("n:!n") or row["n:n"], "target": db_value(row.get(asset["target_parameter"])),
                                "status": decode_status(row.get(asset["status_parameter"]), status),
                                "status_attribute": status}
    return default, states


class RunGuard:
    """One local sender at a time; persist attempt times BEFORE sending, even on failure.

    This guards restarts in this checkout. It cannot coordinate another computer.
    Keep .state private and intact; a crash may require manual lock recovery.
    """
    def __init__(self, folder=None, interval=MIN_SEND_INTERVAL, now=None, sleep=None):
        number(interval, "send interval")
        if interval < MIN_SEND_INTERVAL:
            raise TutorialError(f"Live interval must be at least {MIN_SEND_INTERVAL} seconds per connection.")
        self.folder = Path(folder) if folder is not None else ROOT / ".state"
        self.interval = interval
        self.now, self.sleep = now or time.time, sleep or time.sleep

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.folder / "run.lock"
        try:
            self.lock = self.lock_path.open("x", encoding="utf-8")
        except FileExistsError:
            raise TutorialError("Sender lock exists. Stop the other sender or follow documented crash recovery.") from None
        self.lock.write(str(os.getpid()))
        self.lock.flush()
        self.path = self.folder / "attempts.json"
        try:
            self.attempts = read_json(self.path) if self.path.exists() else {}
            if not isinstance(self.attempts, dict):
                raise TutorialError("Invalid pacing state; preserve it and inspect before sending.")
            for value in self.attempts.values():
                number(value, "persisted attempt time")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def remaining(self, model, connection):
        previous = self.attempts.get(model + "/" + connection)
        if previous is None:
            return 0
        if previous > self.now() + 1:
            raise TutorialError("Clock moved backwards; correct it before sending.")
        return max(0, previous + self.interval - self.now())

    def reserve(self, model, connection):
        while (remaining := self.remaining(model, connection)) > 0:
            self.sleep(min(remaining, 30))
        self.complete(model, connection)

    def complete(self, model, connection):
        # Recording completion too makes the next request wait a full interval
        # even if the preceding request or its intent-log flush took a long time.
        self.attempts[model + "/" + connection] = self.now()
        pending = self.folder / "attempts.tmp"
        with pending.open("w", encoding="utf-8") as target:
            json.dump(self.attempts, target, allow_nan=False)
            target.flush()
            os.fsync(target.fileno())
        pending.replace(self.path)

    def __exit__(self, *args):
        self.lock.close()
        self.lock_path.unlink()


def event(log, kind, **data):
    log.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "kind": kind, **data}, allow_nan=False) + "\n")
    log.flush()
    os.fsync(log.fileno())


def destinations(config, model):
    names = [sensor["ingestion_env"] for sensor in config["sensors"]]
    values = credentials(names=names, prefer_file=True)
    return {sensor["id"]: destination(values[sensor["ingestion_env"]], model, sensor["connection_key"])
            for sensor in config["sensors"]}


def utc_text(stamp_ms):
    return datetime.fromtimestamp(stamp_ms / 1000, timezone.utc).isoformat(timespec="milliseconds")


def submit_reading(client, sensor, model, destination, payload, guard, record, check_stop):
    """Attempt ingestion once and retain the real request window."""
    connection = sensor["connection_key"]
    check_stop()
    guard.reserve(model, connection)
    check_stop()
    started = int(time.time() * 1000)
    record("ingest_intent", sensor=sensor["id"], payload=payload, send_started_utc=utc_text(started))
    try:
        status = client.ingest(destination, payload)
        outcome = {"outcome": "HTTP_ACCEPTED", "http_status": status}
    except ApiError as error:
        status = error.http_status
        unknown = status is None or status == 408 or status >= 500
        outcome = {"outcome": "DELIVERY_UNKNOWN" if unknown else "HTTP_ERROR",
                   "http_status": status, "error": str(error)}
    finally:
        ended = int(time.time() * 1000)
        guard.complete(model, connection)
    record("ingest_outcome", sensor=sensor["id"], send_started_utc=utc_text(started),
           send_ended_utc=utc_text(ended), **outcome)
    return outcome


def write_status(client, sensor, value, status_attribute, record):
    """Use the submitted value and current room target after successful ingestion."""
    sid, asset = sensor["id"], sensor["asset"]
    result = {}
    try:
        state = asset_state(client, sensor, status_attribute)
        status = evaluate(value, state["target"])
        result = {"status": status, "target": state["target"], "previous": state["status"]}
        if status == state["status"]:
            outcome = "STATUS_UNCHANGED"
        else:
            record("mutation_intent", sensor=sid, status=status, target=state["target"])
            stamp = client.mutate(asset["model_urn"], [(asset["element_key"], asset["status_parameter"], status)])
            result["real_mutation_ms"] = stamp
            outcome = "STATUS_UPDATED"
    except Interrupted:
        raise
    except TutorialError as error:
        outcome = "STATUS_FAILED"
        result["error"] = str(error)
    record("status_outcome", sensor=sid, outcome=outcome, **result)
    return outcome


def run(client, config, batches, log, guard, seed_only=False, start_round=1,
        on_progress=None, check_stop=None):
    """Share paced sending and per-lab writeback across the simulator and CLI."""
    if seed_only and (len(batches) != 1 or start_round != 1):
        raise TutorialError("Mapping setup sends exactly one initial round per connection.")
    model, initial = preflight(client, config, mappings=not seed_only, require_write=not seed_only)
    targets = destinations(config, model)  # Validate both secret destinations before sending.
    check_stop = check_stop or (lambda: None)
    for round_number, batch in enumerate(batches, start_round):
        check_stop()
        wait = max(guard.remaining(model, sensor["connection_key"]) for sensor in config["sensors"])
        if wait:
            guard.sleep(wait)
        check_stop()

        def record(kind, **data):
            event(log, kind, round=round_number, **data)
            if on_progress:
                on_progress(kind, {"round": round_number, **data})

        record("round_started")
        successful = True
        outcomes = {}
        for sensor in config["sensors"]:
            sid = sensor["id"]
            payload = batch[sid]
            outcome = submit_reading(client, sensor, model, targets[sid], payload, guard, record, check_stop)
            outcomes[sid] = outcome
            if outcome["outcome"] != "HTTP_ACCEPTED":
                successful = False
            elif not seed_only:
                status = write_status(client, sensor, payload[config["measurement_field"]],
                                      initial[sid]["status_attribute"], record)
                if status == "STATUS_FAILED":
                    successful = False
        if seed_only:
            record("mapping_sample_complete", outcomes=outcomes)
        else:
            record("round_completed", success=successful)
        if not successful:
            return False
    return True
