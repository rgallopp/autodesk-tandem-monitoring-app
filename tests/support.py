"""Invented lab fixtures/in-memory API: never live evidence."""

import base64
import copy
import time

from monitoring.config import ROOT, key, load


def encoded(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def fixture():
    config = load(ROOT / "config/project.example.json")
    config["facility_urn"] = "urn:adsk.dtt:" + encoded(b"f" * 16)
    model = "urn:adsk.dtm:" + encoded(b"m" * 16)
    for index, sensor in enumerate(config["sensors"]):
        sensor["connection_key"] = key(encoded(bytes([index + 1]) * 20), logical=True)
        sensor["parameters"] = {"noise_db": "z:noise"}
        sensor["asset"].update(model_urn=model, element_key=encoded(bytes([index + 3]) * 20),
                               target_parameter="z:target", status_parameter="z:status",
                               number_parameter="r:number", comments_parameter="r:comments")
    return config


def environment(config):
    model = config["facility_urn"].replace("dtt:", "dtm:")
    return {s["ingestion_env"]: f'https://:fixture-secret@tandem.autodesk.com/api/v1/timeseries/models/{model}/streams/{s["connection_key"]}'
            for s in config["sensors"]}


class Clock:
    def __init__(self):
        self.value, self.sleeps = time.time(), []

    def time(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class MemoryClient:
    def __init__(self, config=None, clock=None):
        self.config = copy.deepcopy(config or fixture())
        self.clock = clock or Clock()
        self.default = self.config["facility_urn"].replace("dtt:", "dtm:")
        self.models = [self.default, self.config["sensors"][0]["asset"]["model_urn"]]
        self.access_level = "ReadWrite"
        self.assets, self.records, self.calls = {}, {}, []
        for index, sensor in enumerate(self.config["sensors"]):
            asset = sensor["asset"]
            self.assets[sensor["id"]] = {"k": asset["element_key"], "n:a": 5, "n:n": asset["expected_name"],
                "n:!v": "13.53", "r:number": asset["expected_number"], "r:comments": asset["comments_contains"],
                "z:target": [55.0, 50.0][index]}
            self.records[sensor["id"]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def facility(self, facility):
        self.calls.append(("facility", facility))
        return self.default, self.models

    def schema(self, model):
        attrs = {pid: {"id": pid, "fam": "z", "col": pid[2:], "name": name, "dataType": kind, "context": "e"}
                 for pid, name, kind in [("z:noise", "Noise Level", 3), ("z:target", "Noise Target", 3), ("z:status", "Noise Status", 20)]}
        for pid in ("z:noise", "z:target"):
            attrs[pid].update(forgeSpec="soundPressureLevel", forgeUnit="decibels", forgeSymbol="dB", precision=1)
        attrs["z:status"]["allowedValues"] = {"list": ["Normal", "High"], "map": {"Normal": 1, "High": 2}}
        attrs.update({"r:number": {"id": "r:number", "name": "Number"}, "r:comments": {"id": "r:comments", "name": "Comments"}})
        return attrs

    def scan(self, model, keys=None, columns=None):
        self.calls.append(("scan", model))
        if model == self.default:
            rows = []
            for sensor in self.config["sensors"]:
                asset = sensor["asset"]
                model_bytes = base64.urlsafe_b64decode(asset["model_urn"].split(":")[-1] + "==")
                element_bytes = base64.urlsafe_b64decode(asset["element_key"] + "=")
                reference = encoded(model_bytes + b"\0" * 4 + element_bytes)
                rows.append({"k": key(sensor["connection_key"]), "n:a": 0x01000003, "n:n": sensor["expected_connection_name"],
                             "n:v": "23.60.10.00", "x:p": reference, "x:r": reference})
        else:
            rows = list(self.assets.values())
        if keys:
            wanted = {key(k) for k in keys}
            rows = [row for row in rows if row["k"] in wanted]
        return copy.deepcopy(rows)

    def stream_configs(self, model):
        return {s["connection_key"]: {pid: field for field, pid in s["parameters"].items()} for s in self.config["sensors"]}

    def ingest(self, target, payload):
        sid = next(s["id"] for s in self.config["sensors"] if target[0].endswith(s["connection_key"]))
        self.clock.value += 0.1
        self.calls.append(("ingest", sid, self.clock.time(), copy.deepcopy(payload)))
        self.records[sid].append((int(self.clock.time() * 1000), copy.deepcopy(payload)))
        return 200

    def history(self, model, connection, parameter, start_ms, end_ms):
        self.calls.append(("history", parameter))
        sid = next(s["id"] for s in self.config["sensors"] if s["connection_key"] == connection)
        return [(stamp, payload["noise_db"]) for stamp, payload in self.records[sid] if start_ms <= stamp < end_ms]

    def mutate(self, model, changes):
        self.calls.append(("mutate", model, copy.deepcopy(changes)))
        for element, pid, value in changes:
            sid = next(s["id"] for s in self.config["sensors"] if s["asset"]["element_key"] == element)
            self.assets[sid][pid] = value
        return int(self.clock.time() * 1000)
