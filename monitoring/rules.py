"""Reference rule: one verified dB reading above its model target means High.

Campus support staff decide whether to visit. Revit Comments describe room use;
neither the rule nor the application infers occupancy or a sound source.
"""

from .config import TutorialError, db_value


def evaluate(measurement, target):
    """(verified reading in dB, model target in dB) -> exact restricted Text label."""
    return "High" if db_value(measurement) > db_value(target) else "Normal"


def status_definition(attribute):
    """Verify the actual schema's case-sensitive restricted Text vocabulary."""
    allowed = attribute.get("allowedValues")
    if not isinstance(allowed, dict) or set(allowed.get("list", [])) != {"Normal", "High"}:
        raise TutorialError("Noise Status must restrict Text to exactly Normal and High.")
    mapping = allowed.get("map")
    if (not isinstance(mapping, dict) or set(mapping) != {"Normal", "High"}
            or len({str(v) for v in mapping.values()}) != 2):
        raise TutorialError("Noise Status schema needs an unambiguous Normal/High value map.")
    return mapping


def decode_status(value, attribute):
    """Accept canonical property Text or a schema-proven encoded value, never guess.

    Text mutation writes use the exact labels. Some API representations (notably
    discrete streams) return IDs; decode only an ID from this property's schema.
    """
    mapping = status_definition(attribute)
    if value is None or value == "":
        return None
    if isinstance(value, str) and value in mapping:
        return value
    matches = [label for label, code in mapping.items()
               if not isinstance(value, bool) and str(value) == str(code)]
    if len(matches) != 1:
        raise TutorialError("Stored Noise Status is not a schema-defined Normal/High value.")
    return matches[0]
