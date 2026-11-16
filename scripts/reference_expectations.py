"""OFFLINE expected results only; assumed demonstration targets are not live fallbacks."""

from monitoring.config import ROOT, load
from monitoring.rules import evaluate
from monitoring.simulation import rounds

ASSUMED_DEMONSTRATION_TARGETS = {"room-a": 55.0, "room-b": 50.0}


def expected_rows():
    config = load(ROOT / "config/project.example.json")
    previous = {s["id"]: None for s in config["sensors"]}
    result = []
    for index, batch in enumerate(rounds(config), 1):
        for sensor in config["sensors"]:
            sid = sensor["id"]
            value = batch[sid][config["measurement_field"]]
            status = evaluate(value, ASSUMED_DEMONSTRATION_TARGETS[sid])
            action = "initialize" if previous[sid] is None else "preserve" if previous[sid] == status else "change"
            result.append({"round": index, "room": sensor["label"], "measurement": value,
                           "assumed_target": ASSUMED_DEMONSTRATION_TARGETS[sid], "status": status, "action": action})
            previous[sid] = status
    return result


def render_table():
    lines = ["| Round | Lab | Noise Level (dB) | Assumed target (dB) | Expected Noise Status | Status action |",
             "|---|---|---|---|---|---|"]
    for row in expected_rows():
        lines.append(f"| {row['round']} | {row['room']} | {row['measurement']:.1f} | {row['assumed_target']:.1f} | {row['status']} | {row['action']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print("OFFLINE EXPECTATIONS ONLY. Targets are teaching assumptions; actual timestamps exist only in live evidence.\n")
    print(render_table())
