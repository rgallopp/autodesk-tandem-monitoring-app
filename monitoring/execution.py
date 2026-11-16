"""UI execution controller; all sends use the established CLI workflow."""
import copy
import json
import math
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from .api import TandemClient, ApiError
from .config import ROOT, TutorialError, db_value, read_json
from .rules import evaluate
from .simulation import rounds
from .workflow import RunGuard, event, preflight, run, verify_round

class Interrupted(TutorialError):
    pass

def custom_batch(config, values):
    if set(values) != {s["id"] for s in config["sensors"]}:
        raise TutorialError("Enter one reading per configured lab.")
    return {s["id"]: {config["measurement_field"]: db_value(values[s["id"]])} for s in config["sensors"]}

def planned(config, targets):
    return [{"Round": i, "Lab": s["label"], "Planned noise (dB)": batch[s["id"]][config["measurement_field"]],
             "Current target (dB)": targets[s["id"]], "Expected status": evaluate(batch[s["id"]][config["measurement_field"]], targets[s["id"]])}
            for i, batch in enumerate(rounds(config), 1) for s in config["sensors"]]

def availability(config, folder=None, now=None):
    folder = Path(folder) if folder else ROOT / ".state"
    now = (now or time.time)()
    attempts = read_json(folder / "attempts.json") if (folder / "attempts.json").exists() else {}
    if not isinstance(attempts, dict):
        raise TutorialError("Invalid pacing state.")
    model = config["facility_urn"].replace("urn:adsk.dtt:", "urn:adsk.dtm:", 1)
    waits = {}
    for sensor in config["sensors"]:
        value = attempts.get(model + "/" + sensor["connection_key"])
        if value is not None and (not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value > now + 1):
            raise TutorialError("Pacing state or clock needs checking.")
        waits[sensor["id"]] = max(0, math.ceil(value + 60 - now)) if value is not None else 0
    return {"waits": waits, "busy": (folder / "run.lock").exists(), "review": (folder / "review.json").exists()}

class CheckedClient:
    def __init__(self, client, stop):
        self.client, self.stop = client, stop
    def __getattr__(self, name):
        value = getattr(self.client, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            if self.stop.is_set():
                raise Interrupted("Stopped. An active request may already have completed; inspect partial-round evidence.")
            return value(*args, **kwargs)
        return call

class Controller:
    def __init__(self, folder=None, outputs=None, client_factory=TandemClient, now=None, sleep=None):
        self.folder = Path(folder) if folder else ROOT / ".state"
        self.outputs = Path(outputs) if outputs else ROOT / "outputs"
        self.factory, self.now, self.sleep = client_factory, now or time.time, sleep
        self.mutex = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.state = {"active": False, "phase": "Ready", "round": 0, "completed": 0, "total": 0, "revision": 0, "verified": {}, "audit": None}
    def status(self):
        with self.mutex:
            return copy.deepcopy(self.state)
    def update(self, **data):
        with self.mutex:
            self.state.update(data)
    def stop(self):
        with self.mutex:
            if self.state["active"]:
                self.stop_event.set()
                self.state["phase"] = "Stopping after the active operation"
    def check(self):
        if self.stop_event.is_set():
            raise Interrupted("Stopped before the next operation.")

    def wait(self, seconds):
        until = self.now() + seconds
        while self.now() < until:
            if self.stop_event.is_set():
                raise Interrupted("Stopped during a wait; no queued send will follow.")
            self.update(phase=f"Waiting {math.ceil(until - self.now())} seconds")
            interval = min(1, until - self.now())
            if self.sleep:
                self.sleep(interval)
            else:
                self.stop_event.wait(interval)
        if self.stop_event.is_set():
            raise Interrupted("Stopped during a wait.")
    def progress(self, kind, data):
        if kind == "round_started":
            self.update(round=data["round"], phase="Preparing round")
        elif kind == "ingest_intent":
            self.update(round=data["round"], phase="Sending readings")
        elif kind == "readback_started":
            self.update(phase="Waiting for stored readings")
        elif kind == "mutation_intent":
            self.update(phase="Updating room statuses")
        elif kind == "round_verified":
            with self.mutex:
                self.state["completed"] += 1
                self.state["revision"] += 1
                self.state["verified"] = data["actual"]
                self.state["verified_round"] = data["round"]
                self.state["phase"] = "Round verified"
    def start(self, config, mode, values=None):
        config = copy.deepcopy(config)
        if mode not in ("guided", "custom"):
            raise TutorialError("Select a simulator mode.")
        batches = rounds(config) if mode == "guided" else [custom_batch(config, values or {})]
        with self.mutex:
            if self.state["active"]:
                raise TutorialError("A sending workflow is already active.")
            log = None
            guard = RunGuard(self.folder, now=self.now, sleep=self.wait)
            guard.__enter__()
            try:
                model = config["facility_urn"].replace("urn:adsk.dtt:", "urn:adsk.dtm:", 1)
                if any(guard.remaining(model, s["connection_key"]) > 0 for s in config["sensors"]):
                    raise TutorialError("Cooling down. Wait, then click again; no send was queued.")
                self.outputs.mkdir(parents=True, exist_ok=True)
                path = self.outputs / ("ui-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl")
                log = path.open("x", encoding="utf-8")
                self.stop_event.clear()
                revision = self.state["revision"]
                self.state = {"active": True, "mode": mode, "phase": "Checking connections", "round": 1,
                              "completed": 0, "total": len(batches), "revision": revision, "verified": {}, "audit": path.name}
                self.thread = threading.Thread(target=self.work, args=(config, batches, log, guard), daemon=True)
                self.thread.start()
            except BaseException:
                if log:
                    log.close()
                self.state["active"] = False
                guard.__exit__(None, None, None)
                raise
    def work(self, config, batches, log, guard):
        try:
            event(log, "run_started", mode=self.state["mode"], steps=len(batches), interval=60)
            with self.factory(config["region"], write=True) as client:
                run(CheckedClient(client, self.stop_event), config, batches, log, guard,
                    sleep=self.wait, on_progress=self.progress, check_stop=self.check)
            self.update(phase="Completed")
            event(log, "run_completed", mode=self.state["mode"], success=True)
        except Interrupted as error:
            self.update(phase="Interrupted. No further operations scheduled.")
            event(log, "run_interrupted", error=str(error))
        except TutorialError as error:
            self.update(phase="Failed. Checking any recorded operation.")
            event(log, "run_stopped", error=str(error), note="No automatic retries. Partial or unknown writes possible.")
        except Exception:
            self.update(phase="Failed. Check the saved evidence and configuration.")
            event(log, "run_stopped", error="Unexpected local failure; private details hidden.", note="Partial/unknown writes possible.")
        finally:
            log.close()
            if (self.folder / "review.json").exists():
                self.update(phase="Checking the recorded operation")
                self.reconcile(config, guard)
            guard.__exit__(None, None, None)
            self.update(active=False)
    def retry_verification(self, config):
        with self.mutex:
            if self.state["active"]:
                raise TutorialError("Verification is already active.")
            guard = RunGuard(self.folder, now=self.now, allow_review=True)
            guard.__enter__()
            if not (self.folder / "review.json").exists():
                guard.__exit__(None, None, None)
                return
            self.update(active=True, phase="Checking the recorded attempt", issue=None)
            self.thread = threading.Thread(target=self.retry_work, args=(copy.deepcopy(config), guard), daemon=True)
            self.thread.start()

    def retry_work(self, config, guard):
        try:
            self.reconcile(config, guard)
        finally:
            guard.__exit__(None, None, None)
            self.update(active=False)

    def reconcile(self, config, guard):
        """Resolve this audit only. Never ingests or repeats a mutation intent."""
        try:
            marker = read_json(self.folder / "review.json")
            path = Path(marker["audit"]).resolve()
            if path.parent != self.outputs.resolve():
                raise TutorialError("Recorded evidence location needs checking.")
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            if self.state.get("audit") != path.name:
                started = next((r for r in records if r["kind"] == "run_started"), {})
                completed = [r for r in records if r["kind"] == "round_verified"]
                self.update(audit=path.name, total=started.get("steps", marker["round"]),
                            completed=len(completed), verified=completed[-1]["actual"] if completed else {})
            current = [r for r in records if r.get("round") == marker["round"]]
            intents = [r for r in current if r["kind"] == "ingest_intent"]
            interrupted = any(r["kind"] == "run_interrupted" for r in records)
            mutation = any(r["kind"] == "mutation_intent" for r in current)
            self.update(phase="Checking stored readings", round=marker["round"])
            with self.factory(config["region"], write=not interrupted and not mutation) as client:
                model, states = preflight(client, config)
                batch, bounds, rejected = {}, {}, []
                for sensor in config["sensors"]:
                    sid = sensor["id"]
                    intent = next((r for r in intents if r["sensor"] == sid), None)
                    if not intent:
                        continue
                    outcome = next((r for r in current if r["kind"] == "ingest_outcome" and r["sensor"] == sid), {})
                    start = int(datetime.fromisoformat(intent["send_started_utc"]).timestamp()*1000)
                    rows = client.history(model, sensor["connection_key"], sensor["parameters"][config["measurement_field"]],
                                          start-1000, min(int(self.now()*1000)+1000, start-1000+86400000))
                    matches = [(t,v) for t,v in rows if v == intent["payload"][config["measurement_field"]]]
                    if not matches:
                        code = outcome.get("http_status")
                        if code in (400,401,403,404,405,410,413,415,422,429):
                            rejected.append(f"Lab {sensor['asset']['expected_number']}: request rejected (HTTP {code}); no matching reading retained.")
                            continue
                        reason = f"HTTP {code} was received" if code else "the send outcome is unknown"
                        raise TutorialError(f"Lab {sensor['asset']['expected_number']}: {reason}, but its recorded reading is not returned by Tandem yet.")
                    batch[sid] = intent["payload"]
                    bounds[sid] = (start, matches[-1][0])
                with path.open("a", encoding="utf-8") as log:
                    def record(kind, **data):
                        event(log, kind, **data)
                        if kind == "round_verified":
                            if not any(r["kind"] == "round_verified" for r in current):
                                self.progress(kind, data)
                            guard.verified()
                    if mutation:
                        expected = next(r for r in current if r["kind"] == "rule_expected")
                        for sensor in config["sensors"]:
                            sid = sensor["id"]
                            if states[sid]["target"] != expected["targets"][sid]:
                                raise TutorialError(f"Lab {sensor['asset']['expected_number']}: target changed since evaluation; the recorded status cannot be verified.")
                            if states[sid]["status"] != expected["results"][sid]:
                                raise TutorialError(f"Lab {sensor['asset']['expected_number']}: stored status is {states[sid]['status'] or 'empty'}; waiting to verify {expected['results'][sid]}. The status write will not be repeated.")
                        if len(batch) != len(config["sensors"]):
                            raise TutorialError("Status readback matched, but the recorded measurements remain incomplete.")
                        record("round_verified", round=marker["round"], actual=expected["results"],
                               measurements={sid: {"ingested_ms": bounds[sid][1], "measurement": p[config["measurement_field"]]} for sid,p in batch.items()},
                               unchanged=[], reconciled=True)
                    elif len(batch) == len(config["sensors"]) and not interrupted and not rejected:
                        if getattr(client, "access_level", "Unknown") not in ("ReadWrite", "Manage"):
                            raise TutorialError("Readings are stored, but Edit access is required to finish status evaluation.")
                        self.update(phase="Verifying the recorded round")
                        verify_round(CheckedClient(client,self.stop_event), config, model, batch, bounds, states,
                                     record, marker["round"], read_attempts=3,
                                     sleep=self.sleep or time.sleep)
                    else:
                        record("operation_reconciled", round=marker["round"], note="Interrupted/partial/rejected attempt resolved by reads; not a verified complete round.", rejected=rejected)
                        guard.verified()
                        self.update(phase="Failed: " + " ".join(rejected) if rejected else "Interrupted. Partial results checked; no further operations scheduled.",
                                    revision=self.state["revision"]+1, issue=None)
                        return
                phase = "Completed" if self.state["completed"] == self.state["total"] else f"Round {marker['round']} verified; remaining rounds were not restarted."
                self.update(phase=phase, issue=None)
        except Exception as error:
            if isinstance(error, TutorialError) and not isinstance(error, ApiError):
                issue = str(error)
            elif isinstance(error, ApiError):
                issue = f"Tandem verification request failed (HTTP {error.http_status})." if error.http_status else "Tandem could not be reached to verify the recorded attempt."
            else:
                issue = "Recorded evidence could not be read. Check the saved audit and configuration."
            self.update(issue=issue, phase="Verification unresolved. No additional measurements were sent.")

CONTROLLER = Controller()
