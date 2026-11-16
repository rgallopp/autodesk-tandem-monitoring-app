"""Read actual dB history and stored lab statuses; staff decide whether to visit."""

from datetime import datetime, timezone
import time

from .config import TutorialError, db_value
from .rules import evaluate
from .workflow import preflight


def snapshot(client, config, minutes=30, now_ms=None):
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise TutorialError("Read 1..1440 real minutes.")
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    model, states = preflight(client, config)
    end_ms = now_ms + 1
    history = {}
    for sensor in config["sensors"]:
        values = client.history(model, sensor["connection_key"], sensor["parameters"][config["measurement_field"]], end_ms - minutes * 60000, end_ms)
        history[sensor["id"]] = [{"ingested_ms": stamp, "measurement": db_value(value)} for stamp, value in values]
    cards, trends = [], []
    for sensor in config["sensors"]:
        sid, state = sensor["id"], states[sensor["id"]]
        rows = history[sid]
        if not rows:
            cards.append({"room": state["room_name"], "sensor": sid, "measurement": None,
                          "target": state["target"], "stored_status": state["status"], "ingested_utc": None,
                          "quality": "NO_DATA", "successive_high_readings": None})
            continue
        latest = rows[-1]
        consistent = state["status"] is not None and evaluate(latest["measurement"], state["target"]) == state["status"]
        fresh = 0 <= now_ms - latest["ingested_ms"] <= 300000
        quality = "NOT_EVALUATED" if state["status"] is None else "UNVERIFIED_STATUS" if not consistent else "STALE" if not fresh else "CURRENT_READBACK"
        count = 0
        if quality == "CURRENT_READBACK":
            previous_stamp = None
            for row in reversed(rows):
                if row["measurement"] <= state["target"]:
                    break
                if previous_stamp is not None and previous_stamp - row["ingested_ms"] > config["max_history_gap_seconds"] * 1000:
                    break
                count += 1
                previous_stamp = row["ingested_ms"]
        cards.append({"room": state["room_name"], "sensor": sid, "measurement": latest["measurement"],
                      "target": state["target"], "stored_status": state["status"],
                      "ingested_utc": datetime.fromtimestamp(latest["ingested_ms"] / 1000, timezone.utc).isoformat(),
                      "quality": quality, "successive_high_readings": count if quality == "CURRENT_READBACK" else None})
        previous_stamp = None
        for row in rows:
            gap = None if previous_stamp is None else (row["ingested_ms"] - previous_stamp) / 1000
            trends.append({"room": state["room_name"], "measurement": row["measurement"],
                           "current_target": state["target"],
                           "comparison": "Above current target" if row["measurement"] > state["target"] else "At/below current target",
                           "gap_before_seconds": gap,
                           "quality": "GAP_REVIEW" if gap is not None and gap > config["max_history_gap_seconds"] else "API_READ_BACK",
                           "ingested_utc": datetime.fromtimestamp(row["ingested_ms"] / 1000, timezone.utc).isoformat()})
            previous_stamp = row["ingested_ms"]
    return {"source": "Autodesk Tandem API", "cards": cards, "trends": trends,
            "high_labs": [c["room"] for c in cards if c["quality"] == "CURRENT_READBACK" and c["stored_status"] == "High"]}
