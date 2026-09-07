from __future__ import annotations

from yt_capabilities import APPROXIMATE, EXACT, UNAVAILABLE, capability
from yt_sources import backend_status


def expression_fields(node) -> set[str]:
    if node is None:
        return set()

    kind = node[0]
    if kind in {"and", "or"}:
        return expression_fields(node[1]) | expression_fields(node[2])
    if kind == "not":
        return expression_fields(node[1])
    if kind in {
        "is_null",
        "is_not_null",
        "contains",
        "matches",
        "compare",
        "between",
        "in",
    }:
        return {node[1]}
    return set()


def required_fields(query, where_expression) -> set[str]:
    fields = expression_fields(where_expression)
    if query is not None:
        fields.update(query["fields"])
        if query["order"] is not None:
            fields.add(query["order"])
    if not fields:
        fields.add("id")
    return fields


def available_backends() -> dict[str, bool]:
    return {name: available for name, available, _detail in backend_status()}


def score_backend(backend: str, fields: set[str]) -> tuple[int, list[str], list[str]]:
    approximate: list[str] = []
    unavailable: list[str] = []
    score = 0

    for field in sorted(fields):
        level = capability(backend, field)
        if level == EXACT:
            score += 2
        elif level == APPROXIMATE:
            score += 1
            approximate.append(field)
        else:
            unavailable.append(field)

    return score, approximate, unavailable


def plan_query(query, where_expression, requested_backend: str) -> dict[str, object]:
    fields = required_fields(query, where_expression)
    availability = available_backends()

    candidates = (
        [requested_backend]
        if requested_backend != "auto"
        else ["youtubejs", "yt-dlp"]
    )

    plans: list[dict[str, object]] = []
    for backend in candidates:
        if not availability.get(backend, False):
            continue
        score, approximate, unavailable = score_backend(backend, fields)
        plans.append(
            {
                "backend": backend,
                "fields": sorted(fields),
                "score": score,
                "approximate": approximate,
                "unavailable": unavailable,
            }
        )

    if not plans:
        if requested_backend == "auto":
            raise RuntimeError("no source backend is available")
        raise RuntimeError(f"requested source backend is unavailable: {requested_backend}")

    plans.sort(
        key=lambda plan: (
            len(plan["unavailable"]),
            -int(plan["score"]),
        )
    )
    return plans[0]


def explain_plan(plan: dict[str, object]) -> str:
    lines = [
        f"backend: {plan['backend']}",
        f"fields: {', '.join(plan['fields'])}",
    ]

    approximate = plan["approximate"]
    unavailable = plan["unavailable"]
    if approximate:
        lines.append(f"approximate: {', '.join(approximate)}")
    if unavailable:
        lines.append(f"unavailable: {', '.join(unavailable)}")
    if not approximate and not unavailable:
        lines.append("coverage: exact")

    return "\n".join(lines)
