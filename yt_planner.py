from __future__ import annotations

from yt_capabilities import APPROXIMATE, EXACT, capability
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


def plan_query(
    query,
    where_expression,
    requested_backend: str,
    cache_status: dict[str, object] | None = None,
    offline: bool = False,
) -> dict[str, object]:
    fields = required_fields(query, where_expression)

    if cache_status is not None and (offline or bool(cache_status.get("fresh"))):
        return {
            "mode": "cache",
            "backend": cache_status.get("backend"),
            "fields": sorted(fields),
            "score": None,
            "approximate": [],
            "unavailable": [],
            "cache_fresh": bool(cache_status.get("fresh")),
            "cache_age": int(cache_status.get("age", 0)),
        }

    if offline:
        raise RuntimeError("offline mode requires cached metadata for this source")

    availability = available_backends()
    candidates = [requested_backend] if requested_backend != "auto" else ["youtubejs", "yt-dlp"]

    plans: list[dict[str, object]] = []
    for backend in candidates:
        if not availability.get(backend, False):
            continue
        score, approximate, unavailable = score_backend(backend, fields)
        plans.append(
            {
                "mode": "live",
                "backend": backend,
                "fields": sorted(fields),
                "score": score,
                "approximate": approximate,
                "unavailable": unavailable,
                "cache_fresh": False,
                "cache_age": None,
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


def acquisition_limit(query, where_expression, backend: str | None) -> int | None:
    """Return a source limit only when early termination is provably safe."""
    if query is None or backend != "yt-dlp":
        return None
    if query.get("limit") is None:
        return None
    if where_expression is not None:
        return None
    if query.get("order") is not None:
        return None
    if query.get("distinct"):
        return None
    return int(query["limit"]) + int(query.get("offset") or 0)


def execution_analysis(query, where_expression, backend: str | None) -> dict[str, object]:
    limit = acquisition_limit(query, where_expression, backend)
    return {
        "acquisition_limit": limit,
        "proof": ("plain LIMIT preserves source order" if limit is not None else "full source required"),
    }


def explain_plan(plan: dict[str, object]) -> str:
    lines = [
        f"mode: {plan['mode']}",
        f"fields: {', '.join(plan['fields'])}",
    ]

    if plan["mode"] == "cache":
        freshness = "fresh" if plan["cache_fresh"] else "stale"
        lines.append(f"cache: {freshness}, age {plan['cache_age']}s")
        backend = plan.get("backend")
        if backend:
            lines.append(f"cached backend: {backend}")
        return "\n".join(lines)

    lines.append(f"backend: {plan['backend']}")
    approximate = plan["approximate"]
    unavailable = plan["unavailable"]
    if approximate:
        lines.append(f"approximate: {', '.join(approximate)}")
    if unavailable:
        lines.append(f"unavailable: {', '.join(unavailable)}")
    if not approximate and not unavailable:
        lines.append("coverage: exact")

    return "\n".join(lines)
