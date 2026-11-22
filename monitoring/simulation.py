"""Deterministic configured values, selected by numbered round, with no time payload."""

from .config import TutorialError, db_value


def checkpoint(round_number):
    if round_number == 1:
        return "Before the event"
    if round_number <= 4:
        return "During the event"
    return "After recovery"


def rounds(config, start_round=1, steps=8):
    """One payload per sensor/round. Round numbers are local evidence, not timestamps."""
    available = min(len(s["simulation"]["values"]) for s in config["sensors"])
    if (type(start_round) is not int or type(steps) is not int or start_round < 1
            or not 1 <= steps <= 256 or start_round + steps - 1 > available):
        raise TutorialError("Select increasing numbered rounds within the configured sequence.")
    return [{sensor["id"]: {config["measurement_field"]:
             db_value(sensor["simulation"]["values"][index])} for sensor in config["sensors"]}
            for index in range(start_round - 1, start_round - 1 + steps)]
