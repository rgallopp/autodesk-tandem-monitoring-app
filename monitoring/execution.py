"""UI execution controller; all sends use the established CLI workflow."""
import copy
import json
import math
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from .api import TandemClient
from .config import ROOT, TutorialError, db_value, read_json
from .rules import evaluate
from .simulation import checkpoint, rounds
from .workflow import MIN_SEND_INTERVAL, Interrupted, RunGuard, event, run


def custom_batch(config, values):
    if set(values) != {s["id"] for s in config["sensors"]}:
        raise TutorialError("Enter one reading per configured lab.")
    return {s["id"]: {config["measurement_field"]: db_value(values[s["id"]])} for s in config["sensors"]}

def planned(config, targets):
    return [{"Checkpoint": checkpoint(i), "Round": i, "Lab": s["label"], "Planned noise (dB)": batch[s["id"]][config["measurement_field"]],
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
        waits[sensor["id"]] = max(0, math.ceil(value + MIN_SEND_INTERVAL - now)) if value is not None else 0
    return {"waits": waits, "busy": (folder / "run.lock").exists()}

class CheckedClient:
    def __init__(self, client, stop):
        self.client, self.stop = client, stop
    def __getattr__(self, name):
        value = getattr(self.client, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            if self.stop.is_set():
                raise Interrupted("Stopped before the next Tandem request.")
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
        self.state = {"active": False, "phase": "Ready", "round": 0, "completed": 0, "total": 0, "outcomes": {}, "audit": None}
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
        while (remaining := until - self.now()) > 0:
            if self.stop_event.is_set():
                raise Interrupted("Stopped during a wait.")
            self.update(phase=f"Next round in {math.ceil(remaining)}s")
            interval = min(1, remaining)
            if self.sleep:
                self.sleep(interval)
            else:
                self.stop_event.wait(interval)
        if self.stop_event.is_set():
            raise Interrupted("Stopped during a wait.")
    def progress(self, kind, data):
        with self.mutex:
            if kind == "round_started":
                self.state.update(round=data["round"], phase="Sending readings", outcomes={})
            elif kind in ("ingest_outcome", "status_outcome"):
                lab = self.state["outcomes"].setdefault(data["sensor"], {})
                lab[kind] = {key: value for key, value in data.items() if key not in ("sensor", "round")}
            elif kind == "mutation_intent":
                self.state["phase"] = "Updating room statuses"
            elif kind == "ingest_intent":
                self.state["phase"] = "Sending readings"
            elif kind == "round_completed":
                self.state["completed"] += 1

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
                    raise TutorialError("Cooling down. Send readings when the button becomes available.")
                self.outputs.mkdir(parents=True, exist_ok=True)
                path = self.outputs / ("ui-run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl")
                log = path.open("x", encoding="utf-8")
                self.stop_event.clear()
                self.state = {"active": True, "mode": mode, "phase": "Checking connections", "round": 0,
                              "completed": 0, "total": len(batches), "outcomes": {}, "audit": path.name}
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
            event(log, "run_started", mode=self.state["mode"], steps=len(batches), interval=guard.interval)
            with self.factory(config["region"], write=True) as client:
                success = run(CheckedClient(client, self.stop_event), config, batches, log, guard,
                              on_progress=self.progress, check_stop=self.check)
            self.update(phase="Completed" if success else "Finished with errors")
            event(log, "run_completed", mode=self.state["mode"], success=success)
        except Interrupted as error:
            self.update(phase="Stopped")
            event(log, "run_interrupted", error=str(error))
        except TutorialError as error:
            self.update(phase=f"Run stopped. {error}")
            event(log, "run_stopped", error=str(error))
        except Exception:
            self.update(phase="Run stopped. Check the saved audit and configuration.")
            event(log, "run_stopped", error="Unexpected local failure; private details hidden.")
        finally:
            try:
                log.close()
            finally:
                try:
                    guard.__exit__(None, None, None)
                finally:
                    self.update(active=False)


CONTROLLER = Controller()
