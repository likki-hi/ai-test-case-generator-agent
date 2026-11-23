"""Validation and normalisation of the model's JSON output.

The LLM is never trusted: Python checks every field, assigns the IDs
and only then lets the data reach the UI or the database.
"""
import json
from typing import Any

COLUMNS = ["ID", "Scenario", "Title", "Preconditions", "Steps",
           "Test Data", "Expected Result", "Priority"]
PRIORITIES = ["High", "Medium", "Low"]
SCENARIOS = ["Positive", "Negative", "Edge"]


class ValidationError(Exception):
    """Raised when the model output cannot be turned into valid test cases."""


def _to_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v).strip() for v in value if str(v).strip()) or default
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items()) or default
    text = str(value).strip()
    return text or default


def _steps_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        items = [str(s).strip() for s in value if str(s).strip()]
        return "\n".join(f"{i}. {s.lstrip('0123456789.) ').strip() or s}" for i, s in enumerate(items, 1))
    return _to_text(value)


def normalise_priority(value: Any) -> str:
    text = _to_text(value).capitalize()
    return text if text in PRIORITIES else "Medium"


def normalise_scenario(value: Any) -> str:
    text = _to_text(value).lower()
    if text.startswith("neg"):
        return "Negative"
    if text.startswith("edge") or "bound" in text:
        return "Edge"
    return "Positive"


def validate_test_cases(data: Any) -> list[dict]:
    """Return a clean list of test-case dicts (keys = COLUMNS) or raise ValidationError."""
    if isinstance(data, dict):
        data = data.get("test_cases")
    if not isinstance(data, list) or not data:
        raise ValidationError("The model did not return a 'test_cases' list.")

    cleaned, seen = [], set()
    for item in data:
        if not isinstance(item, dict):
            continue
        title = _to_text(item.get("title"))
        steps = _steps_text(item.get("steps"))
        expected = _to_text(item.get("expected_result"))
        if not (title and steps and expected):
            continue  # required fields missing -> skip this case
        key = title.lower()
        if key in seen:
            continue  # remove duplicates
        seen.add(key)
        cleaned.append({
            "Scenario": normalise_scenario(item.get("scenario_type")),
            "Title": title,
            "Preconditions": _to_text(item.get("preconditions"), "None"),
            "Steps": steps,
            "Test Data": _to_text(item.get("test_data"), "N/A"),
            "Expected Result": expected,
            "Priority": normalise_priority(item.get("priority")),
        })

    if not cleaned:
        raise ValidationError("No valid test cases found (title, steps and expected result are required).")

    for i, case in enumerate(cleaned, 1):  # IDs are assigned by Python, not the model
        case["ID"] = f"TC-{i:02d}"
    return [{col: case[col] for col in COLUMNS} for case in cleaned]


def validate_analysis(data: Any) -> dict:
    """Normalise the analysis JSON; fall back to safe defaults."""
    if not isinstance(data, dict):
        raise ValidationError("The model did not return an analysis object.")
    categories = [c.lower() for c in data.get("scenario_categories", []) if isinstance(c, str)]
    categories = [c for c in categories if c in ("positive", "negative", "edge")]
    return {
        "feature": _to_text(data.get("feature"), "Unnamed feature"),
        "main_purpose": _to_text(data.get("main_purpose")),
        "conditions": [str(c) for c in data.get("conditions", []) if str(c).strip()],
        "is_clear": bool(data.get("is_clear", True)),
        "clarification_question": _to_text(data.get("clarification_question")),
        "assumptions": [str(a) for a in data.get("assumptions", []) if str(a).strip()],
        "scenario_categories": categories or ["positive", "negative", "edge"],
    }


def to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
