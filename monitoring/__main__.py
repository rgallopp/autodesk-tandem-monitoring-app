"""Run `python -m monitoring --help`. Preview is entirely offline; live actions explicit."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .api import TandemClient
from .config import ROOT, TutorialError, key, load, read_json, urn
from .dashboard import snapshot
from .simulation import rounds
from .workflow import RunGuard, event, preflight, run


def discover(client, facility, model=None, element=None):
    default, models = client.facility(facility)
    selected = model or default
    if selected not in models:
        raise TutorialError("Discovery model is outside the facility.")
    schema = client.schema(selected)
    selected_ids = [pid for pid, attr in schema.items() if pid.startswith("z:") or str(attr.get("name", "")).lower() in {"number", "room number", "comments"}]
    columns = ["n:a", "n:n", "n:!n", "n:v", "n:!v", "x:p", "x:r", "x:!r"] + selected_ids
    rows = client.scan(selected, [element] if element else None, columns)
    if model is None:
        rows = [row for row in rows if row.get("n:a") == 0x01000003]
    # Discovery is an inventory, never a name-based selector. Surface ambiguity
    # without discarding candidates or guessing which instance the learner means.
    names, property_names = defaultdict(list), defaultdict(list)
    for row in rows:
        name = row.get("n:!n", row.get("n:n"))
        if isinstance(name, str) and name:
            names[name].append(row["k"])
    for pid, attr in schema.items():
        if pid.startswith("z:") and isinstance(attr.get("name"), str):
            property_names[attr["name"]].append(pid)
    ambiguities = ([{"kind": "element_name", "name": name, "keys": keys}
                    for name, keys in names.items() if len(keys) > 1]
                   + [{"kind": "parameter_name", "name": name, "ids": ids}
                      for name, ids in property_names.items() if len(ids) > 1])
    # No raw source settings or integration secrets. These IDs/property values can
    # still identify a facility: save discovery output only in ignored outputs/.
    return {"source": "Autodesk Tandem API", "default_model": default, "models": models,
            "selected_model": selected,
            "identity_resolution": "Select explicit IDs after checking model identity and saved relationships; names are not unique.",
            "ambiguities": ambiguities,
            "warnings": ["No elements matched this inventory query."] if not rows else [],
            "attributes": [{k: v for k, v in attr.items() if k in {"id", "fam", "col", "name", "category", "dataType", "forgeSpec", "forgeUnit", "forgeSymbol", "context", "precision", "allowedValues"}}
                           for attr in schema.values() if attr["id"] in selected_ids],
            "elements": [{**row, "connection_key": key(row["k"], logical=True)}
                         if row.get("n:a") == 0x01000003 else row for row in rows],
            "source_fields": client.stream_configs(default) if selected == default else {}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "discover", "inspect", "seed", "pilot", "read"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--start-round", type=int, default=1, help="First numbered local round (not sent as a timestamp)")
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--interval", type=float, default=60, help="Minimum real seconds per connection")
    parser.add_argument("--send", action="store_true", help="Required for seed/pilot writes")
    parser.add_argument("--facility", help="Discovery only: facility URN, no filled model config needed")
    parser.add_argument("--region", choices=["US", "EMEA", "AUS"], default="US", help="Discovery only")
    parser.add_argument("--model", help="Discovery only: owning model to inspect")
    parser.add_argument("--element", help="Discovery only: narrow scan to one element key")
    parser.add_argument("--output", type=Path, help="New private outputs/*.json discovery file or *.jsonl pilot log")
    parser.add_argument("--minutes", type=int, default=30, help="Real ingestion history range for read")
    args = parser.parse_args(argv)
    try:
        writing = args.command in {"seed", "pilot"}
        if writing and not args.send:
            raise TutorialError("seed/pilot require --send. Use preview for offline simulation.")
        if args.send and not writing:
            raise TutorialError("--send is only valid with seed or pilot.")
        if args.command == "preview":
            config = load(args.config or ROOT / "config" / "project.example.json")
            for index, batch in enumerate(rounds(config, args.start_round, args.steps if args.steps is not None else 8), 1):
                print(json.dumps({"round": args.start_round + index - 1, "payloads": batch}, allow_nan=False))
            print("Preview only: no credentials read, HTTP requests, or files written.")
            return 0
        if args.command == "discover":
            facility = args.facility
            if facility is None:
                raw = read_json(args.config or ROOT / "config" / "project.json")
                facility = raw.get("facility_urn") if isinstance(raw, dict) else None
            urn(facility, "dtt")
            with TandemClient(args.region) as client:
                data = discover(client, facility, args.model, args.element)
            text = json.dumps(data, indent=2, allow_nan=False)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as output:
                    output.write(text + "\n")
                print("Private discovery written; use its exact owning model IDs and qualified property IDs.")
                if data["ambiguities"] or data["warnings"]:
                    print("Discovery needs identity review: inspect ambiguities/warnings in the inventory before configuring live IDs.")
            else:
                print(text)
            return 0
        config = load(args.config or ROOT / "config" / "project.json", live=True)
        if writing:
            steps = args.steps if args.steps is not None else 1
            if args.command == "seed" and steps != 1:
                raise TutorialError("Seed is exactly one round, only for setting up mappings.")
            batches = rounds(config, args.start_round, steps)
            # Check the interval and reserve the log before opening an HTTP client.
            guard = RunGuard(interval=args.interval)
            output_path = args.output or ROOT / "outputs" / ("pilot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with guard, output_path.open("x", encoding="utf-8") as output:
                event(output, "run_started", mode=args.command, steps=steps, interval=args.interval,
                      evidence="Request outcomes record live attempts; only round_verified establishes pilot readback")
                try:
                    with TandemClient(config["region"], write=args.command == "pilot") as client:
                        accepted = run(client, config, batches, output, guard, seed_only=args.command == "seed", start_round=args.start_round)
                    event(output, "run_completed", mode=args.command, success=accepted)
                except TutorialError as error:
                    event(output, "run_stopped", error=str(error), note="Partial/unknown writes possible; inspect before restarting.")
                    raise
            print("Private audit recorded. Mapping samples are not retention/status verification. Stop after seed to save the mappings." if args.command == "seed" else "Private audit recorded; inspect round_verified events.")
            if not accepted:
                return 1
        else:
            with TandemClient(config["region"]) as client:
                if args.command == "read":
                    print(json.dumps(snapshot(client, config, args.minutes), indent=2, allow_nan=False))
                else:
                    _, states = preflight(client, config)
                    print(json.dumps({"facility_access": client.access_level,
                                      "status_writeback_allowed": client.access_level in ("ReadWrite", "Manage"),
                                      "labs": {sid: {"target_db": state["target"], "noise_status": state["status"]}
                                               for sid, state in states.items()}}, indent=2, allow_nan=False))
        return 0
    except TutorialError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print("Cannot continue; check local file access and configuration. Private details are hidden.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped; partial/unknown writes are possible. Inspect the private audit log before restarting.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
