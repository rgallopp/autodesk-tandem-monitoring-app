"""Three-parameter lab workflow: identity/schema checks, ingestion, readback and status.

Mapping setup is an explicitly separate path: it accepts pending mappings and
never evaluates or writes Noise Status. All measurement writes are single attempts.
"""

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .api import ApiError, associations
from .config import ROOT, TutorialError, credentials, destination, key, db_value, number, read_json
from .rules import evaluate, decode_status, status_definition


class ReadbackPending(ApiError):
    """A well-formed read is incomplete/mismatched; only reads are polled."""


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


def measurements(client, config, model, start_ms, end_ms):
    """Read actual numeric dB history; only Tandem's real ingestion timestamps exist."""
    result = {}
    for sensor in config["sensors"]:
        pid = sensor["parameters"][config["measurement_field"]]
        values = client.history(model, sensor["connection_key"], pid, start_ms, end_ms)
        if not values:
            raise ReadbackPending(f"No retained Noise Level readings for {sensor['id']}; check mappings, bounds and processing.")
        result[sensor["id"]] = [{"ingested_ms": stamp, "measurement": db_value(value)} for stamp, value in values]
    return result

class RunGuard:
    """One local sender at a time; persist attempt times BEFORE sending, even on failure.

    This guards restarts in this checkout. It cannot coordinate another computer.
    Keep .state private and intact; a crash may require manual lock recovery.
    """
    def __init__(self, folder=None, interval=60, now=None, sleep=None, allow_review=False):
        number(interval, "send interval")
        if interval < 60:
            raise TutorialError("Live interval must be at least 60 seconds per connection.")
        self.folder = Path(folder) if folder is not None else ROOT / ".state"
        self.interval = interval
        self.allow_review = allow_review
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
            if (self.folder / "review.json").exists() and not self.allow_review:
                raise TutorialError("An interrupted or failed round needs readback review before another send. Use Retry verification or inspect .state/review.json and its audit.")
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

    def pending(self, log, round_number):
        path = self.folder / "review.json"
        if not path.exists():
            with path.open("x", encoding="utf-8") as output:
                json.dump({"audit": str(Path(log.name).resolve()), "round": round_number}, output)
                output.flush()
                os.fsync(output.fileno())

    def verified(self):
        (self.folder / "review.json").unlink(missing_ok=True)

    def reserve(self, model, connection):
        address = model + "/" + connection
        previous = self.attempts.get(address)
        if previous is not None:
            if previous > self.now() + 1:
                raise TutorialError("Clock moved backwards relative to persisted attempts; correct it before sending.")
            remaining = previous + self.interval - self.now()
            while remaining > 0:
                self.sleep(min(remaining, 30))
                remaining = previous + self.interval - self.now()
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


def send_round(client, config, model, batch, targets, log, guard, round_number, continue_on_error=False, on_event=None, checkpoint=None):
    """Reserve first, record real UTC bounds, send ONCE. Never log endpoints/credentials."""
    report = on_event or (lambda kind, **data: event(log, kind, **data))
    bounds, outcomes = {}, {}
    for sensor in config["sensors"]:
        sid = sensor["id"]
        if checkpoint:
            checkpoint()
        guard.reserve(model, sensor["connection_key"])
        if checkpoint:
            checkpoint()
        started = int(time.time() * 1000)
        report("ingest_intent", round=round_number, sensor=sid, payload=batch[sid],
              send_started_utc=utc_text(started))
        try:
            status = client.ingest(targets[sid], batch[sid])
            outcome = {"outcome": "HTTP_ACCEPTED", "http_status": status}
        except ApiError as error:
            outcome = {"outcome": "HTTP_ERROR" if error.http_status else "DELIVERY_UNKNOWN",
                       "http_status": error.http_status, "error": str(error)}
        finally:
            ended = int(time.time() * 1000)
            guard.complete(model, sensor["connection_key"])
        bounds[sid] = (started, ended)
        outcomes[sid] = outcome
        report("ingest_outcome", round=round_number, sensor=sid, send_started_utc=utc_text(started),
              send_ended_utc=utc_text(ended), **outcome)
        print(f"{sensor['label']}: {outcome['outcome']}; HTTP {outcome['http_status']}; UTC {utc_text(started)} to {utc_text(ended)}", flush=True)
        if outcome["outcome"] != "HTTP_ACCEPTED" and not continue_on_error:
            break
    return bounds, outcomes


def verify_properties(client, config, expected, states):
    actual = {}
    for sensor in config["sensors"]:
        sid = sensor["id"]
        state = asset_state(client, sensor, states[sid]["status_attribute"])
        if state["target"] != states[sid]["target"]:
            raise ApiError("Room target changed during verification; this round is not verified.")
        if state["status"] != expected[sid]:
            raise ReadbackPending("Stored Noise Status does not match the rule result; no mutation retry.")
        actual[sid] = state["status"]
    return actual


def verify_round(client, config, model, batch, bounds, initial, record, round_number,
                 read_attempts=13, sleep=time.sleep, rule=evaluate):
    """Complete an already-sent round; never ingests measurements."""
    for attempt in range(read_attempts):
        try:
            stored = measurements(client, config, model, min(v[0] for v in bounds.values()) - 1000,
                                  int(time.time() * 1000) + 1000)
            for sensor in config["sensors"]:
                sid = sensor["id"]
                latest = stored[sid][-1]
                if latest["ingested_ms"] < bounds[sid][0] - 1000 or latest["measurement"] != batch[sid][config["measurement_field"]]:
                    raise ReadbackPending("Latest retained dB value does not match this request's real UTC window/value.")
            break
        except ReadbackPending:
            if attempt + 1 == read_attempts:
                raise
            sleep(5)
    states = {sensor["id"]: asset_state(client, sensor, initial[sensor["id"]]["status_attribute"])
              for sensor in config["sensors"]}
    expected, changes = {}, defaultdict(list)
    for sensor in config["sensors"]:
        sid, asset = sensor["id"], sensor["asset"]
        result = rule(stored[sid][-1]["measurement"], states[sid]["target"])
        expected[sid] = result
        if result != states[sid]["status"]:
            # Restricted Text properties are mutated using their exact labels.
            changes[asset["model_urn"]].append((asset["element_key"], asset["status_parameter"], result))
    record("rule_expected", round=round_number, results=expected,
          previous={sid: state["status"] for sid, state in states.items()},
          targets={sid: state["target"] for sid, state in states.items()})
    for sensor in config["sensors"]:
        sid = sensor["id"]
        current = asset_state(client, sensor, initial[sid]["status_attribute"])
        if (current["target"], current["status"]) != (states[sid]["target"], states[sid]["status"]):
            raise ApiError("Room target/status changed concurrently; no further mutation attempted.")
    for model_urn, updates in changes.items():
        record("mutation_intent", round=round_number, property_count=len(updates))
        stamp = client.mutate(model_urn, updates)
        record("mutation_accepted", round=round_number, real_mutation_ms=stamp)
    for attempt in range(read_attempts):
        try:
            actual = verify_properties(client, config, expected, states)
            break
        except ReadbackPending:
            if attempt + 1 == read_attempts:
                raise
            sleep(5)
    record("round_verified", round=round_number, actual=actual,
          measurements={sid: rows[-1] for sid, rows in stored.items()},
          unchanged=[sid for sid in expected if expected[sid] == states[sid]["status"]])
    print(f"Round {round_number}: actual dB readings and stored Noise Status verified.", flush=True)


def run(client, config, batches, log, guard, seed_only=False, rule=evaluate, read_attempts=13,
        sleep=time.sleep, start_round=1, on_progress=None, check_stop=None):
    def record(kind, **data):
        if kind == "ingest_intent":
            guard.pending(log, data["round"])
        event(log, kind, **data)
        if on_progress:
            on_progress(kind, data)
        if kind == "round_verified":
            guard.verified()

    if not 1 <= read_attempts <= 25:
        raise TutorialError("Use 1..25 readback attempts.")
    if seed_only and (len(batches) != 1 or start_round != 1):
        raise TutorialError("Mapping setup sends exactly one initial round per connection.")
    model, initial = preflight(client, config, mappings=not seed_only, require_write=not seed_only)
    targets = destinations(config, model)  # Both secret destinations checked before either POST.
    for index, batch in enumerate(batches):
        round_number = start_round + index
        record("round_started", round=round_number)
        bounds, outcomes = send_round(client, config, model, batch, targets, log, guard, round_number,
                                     continue_on_error=seed_only, on_event=record, checkpoint=check_stop)
        all_accepted = len(outcomes) == len(config["sensors"]) and all(v["outcome"] == "HTTP_ACCEPTED" for v in outcomes.values())
        if seed_only:
            record("mapping_sample_complete", outcomes=outcomes,
                  note="Mapping bootstrap only. No retained-history, rule or status-writeback claim.")
            if all_accepted:
                guard.verified()
            return all_accepted
        if not all_accepted:
            raise ApiError("Round stopped after a failed/unknown ingestion; no status result written or automatic resend.")
        record("readback_started", round=round_number)
        verify_round(client, config, model, batch, bounds, initial, record, round_number,
                     read_attempts=read_attempts, sleep=sleep, rule=rule)
    return True
