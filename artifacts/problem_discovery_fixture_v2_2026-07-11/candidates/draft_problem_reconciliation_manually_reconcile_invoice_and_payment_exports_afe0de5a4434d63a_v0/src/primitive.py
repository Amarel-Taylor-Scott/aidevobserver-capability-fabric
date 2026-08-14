"""Generated deterministic candidate primitive.

This module is candidate material.  It performs no network, filesystem,
subprocess, secret, clock, or random operation.
"""

from __future__ import annotations

from typing import Any


def _require_payload(payload: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError("missing required fields: " + ",".join(missing))
    return payload


def adapter(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "field_map"))
    if not isinstance(data["records"], list) or not isinstance(data["field_map"], dict):
        raise ValueError("records must be a list and field_map must be an object")
    rows = [{target: record.get(source) for source, target in sorted(data["field_map"].items())}
            for record in data["records"] if isinstance(record, dict)]
    return {"records": rows, "record_count": len(rows)}


def reconciliation(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("left", "right", "key"))
    if not isinstance(data["left"], list) or not isinstance(data["right"], list) or not isinstance(data["key"], str):
        raise ValueError("left/right must be lists and key must be text")
    key = data["key"]
    left = {row.get(key): row for row in data["left"] if isinstance(row, dict) and key in row}
    right = {row.get(key): row for row in data["right"] if isinstance(row, dict) and key in row}
    shared = sorted(set(left) & set(right), key=str)
    return {
        "matched": [{"key": value, "left": left[value], "right": right[value]} for value in shared],
        "left_only": [left[value] for value in sorted(set(left) - set(right), key=str)],
        "right_only": [right[value] for value in sorted(set(right) - set(left), key=str)],
    }


def validation(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "required_fields"))
    if not isinstance(data["records"], list) or not isinstance(data["required_fields"], list):
        raise ValueError("records and required_fields must be lists")
    errors = []
    valid = []
    for index, record in enumerate(data["records"]):
        if not isinstance(record, dict):
            errors.append({"index": index, "missing": [], "error": "not_an_object"})
            continue
        missing = [field for field in data["required_fields"] if record.get(field) in (None, "")]
        if missing:
            errors.append({"index": index, "missing": missing, "error": "required_field_missing"})
        else:
            valid.append(record)
    return {"valid_records": valid, "errors": errors, "valid": not errors}


def aggregation(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("items", "group_by"))
    if not isinstance(data["items"], list) or not isinstance(data["group_by"], str):
        raise ValueError("items must be a list and group_by must be text")
    value_field = data.get("value_field")
    groups: dict[str, dict[str, Any]] = {}
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        group = str(item.get(data["group_by"], "unknown"))
        bucket = groups.setdefault(group, {"group": group, "count": 0, "sum": 0.0})
        bucket["count"] += 1
        if value_field and isinstance(item.get(value_field), (int, float)):
            bucket["sum"] += float(item[value_field])
    return {"groups": [groups[key] for key in sorted(groups)], "group_count": len(groups)}


def monitoring(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("events", "rules"))
    if not isinstance(data["events"], list) or not isinstance(data["rules"], list):
        raise ValueError("events and rules must be lists")
    alerts = []
    for index, event in enumerate(data["events"]):
        text = " ".join(str(value) for value in event.values()).lower() if isinstance(event, dict) else str(event).lower()
        matched = sorted({str(rule).lower() for rule in data["rules"] if str(rule).lower() in text})
        if matched:
            alerts.append({"event_index": index, "matched_rules": matched, "event": event})
    return {"alerts": alerts, "alert_count": len(alerts)}


def lookup(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "query"))
    if not isinstance(data["records"], list) or not isinstance(data["query"], str):
        raise ValueError("records must be a list and query must be text")
    query = data["query"].casefold()
    fields = data.get("fields") or []
    matches = []
    for index, record in enumerate(data["records"]):
        if not isinstance(record, dict):
            continue
        values = [record.get(field, "") for field in fields] if fields else record.values()
        haystack = " ".join(str(value) for value in values).casefold()
        if query in haystack:
            matches.append({"index": index, "record": record})
    return {"matches": matches, "match_count": len(matches)}


def triage(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("items", "priority_terms"))
    if not isinstance(data["items"], list) or not isinstance(data["priority_terms"], dict):
        raise ValueError("items must be a list and priority_terms must be an object")
    ranked = []
    for index, item in enumerate(data["items"]):
        text = " ".join(str(value) for value in item.values()).casefold() if isinstance(item, dict) else str(item).casefold()
        score = sum(float(weight) for term, weight in data["priority_terms"].items() if str(term).casefold() in text)
        ranked.append({"source_index": index, "priority_score": score, "item": item})
    ranked.sort(key=lambda row: (-row["priority_score"], row["source_index"]))
    return {"queue": ranked, "item_count": len(ranked)}


def handoff(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("items", "routing_rules"))
    if not isinstance(data["items"], list) or not isinstance(data["routing_rules"], list):
        raise ValueError("items and routing_rules must be lists")
    assignments, unrouted = [], []
    for index, item in enumerate(data["items"]):
        matched = None
        for rule in data["routing_rules"]:
            if not isinstance(rule, dict):
                continue
            field, equals = rule.get("field"), rule.get("equals")
            if isinstance(item, dict) and item.get(field) == equals:
                matched = rule.get("destination")
                break
        target = {"source_index": index, "item": item}
        if matched is None:
            unrouted.append(target)
        else:
            assignments.append({**target, "destination": matched})
    return {"assignments": assignments, "unrouted": unrouted}


def extraction(payload: Any) -> dict[str, Any]:
    return adapter(payload)


def policy(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("records", "rules"))
    if not isinstance(data["records"], list) or not isinstance(data["rules"], list):
        raise ValueError("records and rules must be lists")
    decisions = []
    for index, record in enumerate(data["records"]):
        failures = []
        for rule in data["rules"]:
            if isinstance(rule, dict) and isinstance(record, dict):
                field = rule.get("field")
                if "equals" in rule and record.get(field) != rule["equals"]:
                    failures.append(rule.get("id", field))
                if "required" in rule and rule["required"] and record.get(field) in (None, ""):
                    failures.append(rule.get("id", field))
        decisions.append({"source_index": index, "allow": not failures, "failed_rules": sorted(set(failures))})
    return {"decisions": decisions, "all_allowed": all(row["allow"] for row in decisions)}


def scheduling(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("tasks", "slots"))
    if not isinstance(data["tasks"], list) or not isinstance(data["slots"], list):
        raise ValueError("tasks and slots must be lists")
    assignments = [{"task": task, "slot": data["slots"][index]}
                   for index, task in enumerate(data["tasks"]) if index < len(data["slots"])]
    return {"assignments": assignments, "unscheduled": data["tasks"][len(assignments):]}


def sync(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("source", "target", "key"))
    if not isinstance(data["source"], list) or not isinstance(data["target"], list) or not isinstance(data["key"], str):
        raise ValueError("source/target must be lists and key must be text")
    key = data["key"]
    source = {row.get(key): row for row in data["source"] if isinstance(row, dict) and key in row}
    target = {row.get(key): row for row in data["target"] if isinstance(row, dict) and key in row}
    creates = [source[value] for value in sorted(set(source) - set(target), key=str)]
    updates = [{"before": target[value], "after": source[value]} for value in sorted(set(source) & set(target), key=str)
               if source[value] != target[value]]
    deletes = [target[value] for value in sorted(set(target) - set(source), key=str)]
    return {"creates": creates, "updates": updates, "deletes": deletes}


def workflow(payload: Any) -> dict[str, Any]:
    data = _require_payload(payload, ("steps", "triggers"))
    if not isinstance(data["steps"], list) or not isinstance(data["triggers"], list):
        raise ValueError("steps and triggers must be lists")
    ordered_steps = []
    seen = set()
    for index, step in enumerate(data["steps"]):
        if not isinstance(step, dict) or not step.get("id") or not step.get("action"):
            raise ValueError("every step requires id and action")
        if step["id"] in seen:
            raise ValueError("step ids must be unique")
        seen.add(step["id"])
        ordered_steps.append({"index": index, "id": step["id"], "action": step["action"], "after": step.get("after")})
    missing_dependencies = sorted({row["after"] for row in ordered_steps if row["after"] and row["after"] not in seen})
    return {"ordered_steps": ordered_steps, "triggers": data["triggers"], "missing_dependencies": missing_dependencies,
            "ready_for_domain_review": not missing_dependencies}


FUNCTION = reconciliation


def run(payload: Any) -> dict[str, Any]:
    """Run the selected deterministic candidate operation."""
    return FUNCTION(payload)
