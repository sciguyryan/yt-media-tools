"""Deterministic console and Graphviz presentation for explain plans."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
import textwrap
from typing import Any

EXPLANATION_SCHEMA_VERSION = 1

STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_DEFERRED = "deferred"
STATUS_ELIMINATED = "eliminated"
STATUS_INFORMATION = "information"

_ANSI = {
    "heading": "\x1b[1;36m",
    STATUS_APPLIED: "\x1b[32m",
    STATUS_REJECTED: "\x1b[33m",
    STATUS_DEFERRED: "\x1b[36m",
    STATUS_ELIMINATED: "\x1b[35m",
    STATUS_INFORMATION: "\x1b[34m",
    "dim": "\x1b[2m",
    "reset": "\x1b[0m",
}


@dataclass(frozen=True)
class ExplainNode:
    """One deterministic node in the presentation-level explain graph."""

    node_id: str
    label: str
    detail: str
    status: str = STATUS_INFORMATION
    shape: str = "box"


@dataclass(frozen=True)
class ExplainEdge:
    """One directed relation between presentation-level explain nodes."""

    source: str
    target: str
    label: str = ""
    style: str = "solid"


@dataclass(frozen=True)
class ExplainGraph:
    """Presentation-level explanation graph derived from machine explain data."""

    schema_version: int
    nodes: tuple[ExplainNode, ...]
    edges: tuple[ExplainEdge, ...]


def _status_for_stage(stage: dict[str, Any]) -> str:
    return STATUS_APPLIED if stage.get("required") else STATUS_DEFERRED


def build_explain_graph(payload: dict[str, Any]) -> ExplainGraph:
    """Build a deterministic graph from the machine-readable explain payload."""
    nodes: list[ExplainNode] = [
        ExplainNode(
            "query",
            "Query",
            str(payload.get("normalised_query") or payload.get("query") or ""),
            STATUS_INFORMATION,
            "box",
        )
    ]
    edges: list[ExplainEdge] = []

    boundaries = payload.get("source_boundaries", [])
    if not isinstance(boundaries, list):
        boundaries = []

    for index, boundary in enumerate(boundaries):
        if not isinstance(boundary, dict):
            continue
        source_id = f"source_{index}"
        source_name = str(boundary.get("source") or "source")
        facet = boundary.get("facet")
        source_label = source_name + (f" OF {facet}" if facet else "")
        if boundary.get("branch_empty"):
            source_status = STATUS_ELIMINATED
            source_detail = "branch eliminated before acquisition"
        else:
            source_status = STATUS_APPLIED
            source_detail = (
                f"acquisition={boundary.get('acquisition', 'unknown')}; "
                f"cost={boundary.get('heuristics', {}).get('cost_tier', boundary.get('cost_class', 'unknown'))}"
            )
        nodes.append(ExplainNode(source_id, source_label, source_detail, source_status, "box"))
        edges.append(ExplainEdge("query", source_id, "source"))

        previous = source_id
        stages = boundary.get("acquisition_stages", [])
        required_stages = (
            [stage for stage in stages if isinstance(stage, dict) and stage.get("required")]
            if isinstance(stages, list)
            else []
        )
        heuristics = boundary.get("heuristics", {})
        deferred_names = set(heuristics.get("deferred_expensive_stages") or [] if isinstance(heuristics, dict) else [])
        early_stage_names = {"enumerate-identities", "basic-metadata"}
        early_stages = [stage for stage in required_stages if str(stage.get("name") or "") in early_stage_names]
        later_stages = [stage for stage in required_stages if str(stage.get("name") or "") not in early_stage_names]

        def append_stage(stage: dict[str, Any], stage_index: int) -> None:
            nonlocal previous
            stage_id = f"source_{index}_stage_{stage_index}"
            fields = stage.get("fields") or []
            field_text = ", ".join(str(item) for item in fields) if fields else "no named fields"
            stage_name = str(stage.get("name") or "metadata stage")
            deferred = stage_name in deferred_names
            nodes.append(
                ExplainNode(
                    stage_id,
                    stage_name,
                    field_text,
                    STATUS_DEFERRED if deferred else _status_for_stage(stage),
                    "box",
                )
            )
            edges.append(
                ExplainEdge(
                    previous,
                    stage_id,
                    "survivors" if deferred else "then",
                    "dashed" if deferred else "solid",
                )
            )
            previous = stage_id

        for stage_index, stage in enumerate(early_stages):
            append_stage(stage, stage_index)

        predicate = boundary.get("pre_acquisition_predicates", [])
        if isinstance(predicate, list) and predicate:
            predicate_id = f"source_{index}_predicate"
            nodes.append(
                ExplainNode(
                    predicate_id,
                    "Enumeration predicate gate",
                    " AND ".join(str(item) for item in predicate),
                    STATUS_APPLIED,
                    "diamond",
                )
            )
            edges.append(ExplainEdge(previous, predicate_id, "filter"))
            previous = predicate_id

        for offset, stage in enumerate(later_stages, start=len(early_stages)):
            append_stage(stage, offset)

    limit = payload.get("limit_aware_termination")
    if isinstance(limit, dict) and limit.get("applicable"):
        eligible = bool(limit.get("eligible"))
        limit_id = "limit_termination"
        nodes.append(
            ExplainNode(
                limit_id,
                "LIMIT-aware termination",
                str(limit.get("reason") or ""),
                STATUS_APPLIED if eligible else STATUS_REJECTED,
                "diamond",
            )
        )
        edges.append(ExplainEdge("query", limit_id, "decision"))

    ctes = payload.get("cte_dependencies", [])
    if isinstance(ctes, list):
        for index, dependency in enumerate(ctes):
            if not isinstance(dependency, dict):
                continue
            cte_id = f"cte_{index}"
            pruned = dependency.get("pruned_outputs") or []
            status = STATUS_APPLIED if dependency.get("pruning_applied") else STATUS_INFORMATION
            detail = (
                "pruned outputs: " + ", ".join(str(item) for item in pruned)
                if pruned
                else str(dependency.get("reason") or "")
            )
            nodes.append(
                ExplainNode(
                    cte_id,
                    f"CTE {dependency.get('name', index + 1)}",
                    detail,
                    status,
                    "box",
                )
            )
            edges.append(ExplainEdge("query", cte_id, "dependency"))

    return ExplainGraph(EXPLANATION_SCHEMA_VERSION, tuple(nodes), tuple(edges))


def graph_to_json(graph: ExplainGraph) -> dict[str, Any]:
    """Serialise the presentation graph without renderer-specific styling."""
    return {
        "schema_version": graph.schema_version,
        "nodes": [
            {
                "id": node.node_id,
                "label": node.label,
                "detail": node.detail,
                "status": node.status,
                "shape": node.shape,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "label": edge.label,
                "style": edge.style,
            }
            for edge in graph.edges
        ],
    }


def explain_decisions(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Return deterministic applied/rejected/deferred decisions for diagnostics."""
    decisions: list[dict[str, str]] = []

    optimiser = payload.get("predicate_optimiser")
    if isinstance(optimiser, dict):
        if optimiser.get("status") == "deferred":
            decisions.append(
                {
                    "category": "predicate optimisation",
                    "status": STATUS_DEFERRED,
                    "decision": "optimiser evaluation",
                    "reason": str(optimiser.get("reason") or ""),
                }
            )
        elif optimiser.get("changed"):
            rewrites = optimiser.get("rewrites") or []
            rules = ", ".join(str(item.get("rule")) for item in rewrites if isinstance(item, dict) and item.get("rule"))
            decisions.append(
                {
                    "category": "predicate optimisation",
                    "status": STATUS_APPLIED,
                    "decision": rules or "safe rewrite",
                    "reason": "one or more semantics-preserving optimiser rewrites were applied",
                }
            )

    predicate = payload.get("predicate_stages")
    if isinstance(predicate, dict):
        enumeration_terms = predicate.get("enumeration_terms") or []
        residual_terms = predicate.get("residual_terms") or []
        if enumeration_terms:
            decisions.append(
                {
                    "category": "predicate staging",
                    "status": STATUS_APPLIED,
                    "decision": "enumeration-stage filtering",
                    "reason": str(predicate.get("reason") or ""),
                }
            )
        if residual_terms:
            decisions.append(
                {
                    "category": "predicate staging",
                    "status": STATUS_DEFERRED,
                    "decision": "residual predicate evaluation",
                    "reason": "remaining predicates require a later authoritative stage",
                }
            )

    for boundary in payload.get("source_boundaries", []) or []:
        if not isinstance(boundary, dict):
            continue
        label = str(boundary.get("source") or "source")
        acquisition = str(boundary.get("acquisition") or "")
        acquisition_reason = str(boundary.get("acquisition_reason") or "")
        if acquisition == "full" and acquisition_reason:
            decisions.append(
                {
                    "category": "bounded acquisition",
                    "status": STATUS_REJECTED,
                    "decision": label,
                    "reason": acquisition_reason,
                }
            )
        elif acquisition not in {"", "skip", "full"}:
            decisions.append(
                {
                    "category": "acquisition strategy",
                    "status": STATUS_APPLIED,
                    "decision": f"{label}: {acquisition}",
                    "reason": acquisition_reason or "a safe bounded acquisition strategy is available",
                }
            )

        if boundary.get("pre_acquisition_predicates"):
            decisions.append(
                {
                    "category": "source-boundary predicate pushdown",
                    "status": STATUS_APPLIED,
                    "decision": label,
                    "reason": "authoritative predicate terms can reject candidates before detailed metadata acquisition",
                }
            )

        if boundary.get("branch_empty"):
            decisions.append(
                {
                    "category": "branch elimination",
                    "status": STATUS_ELIMINATED,
                    "decision": label,
                    "reason": "static or capability proof establishes an empty branch",
                }
            )
        heuristics = boundary.get("heuristics")
        if isinstance(heuristics, dict) and heuristics.get("deferred_expensive_stages"):
            decisions.append(
                {
                    "category": "metadata acquisition",
                    "status": STATUS_DEFERRED,
                    "decision": ", ".join(str(item) for item in heuristics["deferred_expensive_stages"]),
                    "reason": str(heuristics.get("reason") or ""),
                }
            )

    limit = payload.get("limit_aware_termination")
    if isinstance(limit, dict) and limit.get("applicable"):
        decisions.append(
            {
                "category": "LIMIT termination",
                "status": STATUS_APPLIED if limit.get("eligible") else STATUS_REJECTED,
                "decision": str(limit.get("mode") or "none"),
                "reason": str(limit.get("reason") or ""),
            }
        )

    for dependency in payload.get("cte_dependencies", []) or []:
        if not isinstance(dependency, dict):
            continue
        decisions.append(
            {
                "category": "CTE projection pruning",
                "status": STATUS_APPLIED if dependency.get("pruning_applied") else STATUS_REJECTED,
                "decision": str(dependency.get("name") or "CTE"),
                "reason": str(dependency.get("reason") or ""),
            }
        )

    return decisions


def _paint(text: str, status: str, *, colour: bool) -> str:
    if not colour:
        return text
    prefix = _ANSI.get(status, "")
    return f"{prefix}{text}{_ANSI['reset']}" if prefix else text


def render_console_overview(
    payload: dict[str, Any],
    *,
    unicode: bool,
    colour: bool,
) -> str:
    """Render a compact deterministic plan/decision overview."""
    graph = build_explain_graph(payload)
    decisions = explain_decisions(payload)

    if unicode:
        branch, last, vertical, space, arrow = "├─ ", "└─ ", "│  ", "   ", "→"
        heading_rule = "═"
    else:
        branch, last, vertical, space, arrow = "+-- ", "`-- ", "|   ", "    ", "->"
        heading_rule = "="

    title = _paint("Query plan overview", "heading", colour=colour)
    lines = [title, heading_rule * 19]

    roots = [node for node in graph.nodes if node.node_id == "query"]
    if roots:
        lines.append(roots[0].detail or "query")

    children: dict[str, list[tuple[ExplainEdge, ExplainNode]]] = {}
    by_id = {node.node_id: node for node in graph.nodes}
    for edge in graph.edges:
        target = by_id.get(edge.target)
        if target is not None:
            children.setdefault(edge.source, []).append((edge, target))

    def walk(parent: str, prefix: str = "") -> None:
        items = children.get(parent, [])
        for index, (edge, node) in enumerate(items):
            is_last = index == len(items) - 1
            connector = last if is_last else branch
            status = node.status.upper()
            label = f"{node.label} [{status}]"
            lines.append(prefix + connector + _paint(label, node.status, colour=colour))
            child_prefix = prefix + (space if is_last else vertical)
            if node.detail:
                lines.append(child_prefix + space + node.detail)
            walk(node.node_id, child_prefix)

    walk("query")

    if decisions:
        lines.extend(["", _paint("Planner decisions", "heading", colour=colour), heading_rule * 17])
        for index, item in enumerate(decisions):
            connector = last if index == len(decisions) - 1 else branch
            status = item["status"]
            lines.append(
                connector
                + _paint(
                    f"{item['category']}: {item['decision']} [{status.upper()}]",
                    status,
                    colour=colour,
                )
            )
            reason_prefix = space if index == len(decisions) - 1 else vertical
            lines.append(f"{reason_prefix}{space}{arrow} {item['reason']}")

    return "\n".join(lines)


def _dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _dot_wrap(value: str, *, width: int = 48) -> str:
    """Wrap human labels before DOT escaping to avoid very wide SVG plans."""
    parts: list[str] = []
    for paragraph in value.splitlines() or [""]:
        wrapped = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
        )
        parts.extend(wrapped or [""])
    return "\n".join(parts)


def graph_to_dot(graph: ExplainGraph) -> str:
    """Return deterministic Graphviz DOT for an explanation graph."""
    lines = [
        "digraph yt_discover_explain {",
        '  graph [rankdir="TB", bgcolor="transparent", pad="0.25", nodesep="0.35", ranksep="0.55"];',
        '  node [fontname="DejaVu Sans", fontsize="10", style="rounded,filled", margin="0.12,0.08"];',
        '  edge [fontname="DejaVu Sans", fontsize="9"];',
    ]
    fill = {
        STATUS_APPLIED: "#e8f5e9",
        STATUS_REJECTED: "#fff3e0",
        STATUS_DEFERRED: "#e3f2fd",
        STATUS_ELIMINATED: "#f3e5f5",
        STATUS_INFORMATION: "#f5f5f5",
    }
    border = {
        STATUS_APPLIED: "#2e7d32",
        STATUS_REJECTED: "#ef6c00",
        STATUS_DEFERRED: "#1565c0",
        STATUS_ELIMINATED: "#7b1fa2",
        STATUS_INFORMATION: "#616161",
    }
    for node in graph.nodes:
        shape = "diamond" if node.shape == "diamond" else "box"
        label = _dot_wrap(node.label)
        if node.detail:
            label += "\n" + _dot_wrap(node.detail)
        lines.append(
            f'  "{_dot_escape(node.node_id)}" '
            f'[shape="{shape}", label="{_dot_escape(label)}", '
            f'fillcolor="{fill[node.status]}", color="{border[node.status]}"];'
        )
    for edge in graph.edges:
        label = f', label="{_dot_escape(edge.label)}"' if edge.label else ""
        style = "dashed" if edge.style == "dashed" else "solid"
        lines.append(f'  "{_dot_escape(edge.source)}" -> "{_dot_escape(edge.target)}" [style="{style}"{label}];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_svg(payload: dict[str, Any]) -> str:
    """Render the explain graph to SVG using an optional Graphviz executable."""
    dot = shutil.which("dot")
    if dot is None:
        raise RuntimeError(
            "Graphviz 'dot' is required for SVG explain rendering; install Graphviz or use text/json explain output"
        )
    graph = build_explain_graph(payload)
    source = graph_to_dot(graph)
    completed = subprocess.run(
        [dot, "-Tsvg"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Graphviz returned a non-zero status"
        raise RuntimeError(f"Graphviz SVG rendering failed: {detail}")
    svg_lines = completed.stdout.splitlines()
    filtered: list[str] = []
    skipping_generator_comment = False
    for line in svg_lines:
        if line.startswith("<!-- Generated by graphviz version "):
            skipping_generator_comment = True
            continue
        if skipping_generator_comment:
            if line.rstrip().endswith("-->"):
                skipping_generator_comment = False
            continue
        filtered.append(line)
    return "\n".join(filtered) + "\n"


def terminal_supports_unicode(stream: Any) -> bool:
    """Return whether a stream encoding can represent the chosen safe glyph set."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    sample = "│├└─→═"
    try:
        sample.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def resolve_console_modes(
    *,
    stream: Any,
    colour_mode: str,
    unicode_mode: str,
) -> tuple[bool, bool]:
    """Resolve auto/always/never console presentation choices."""
    is_tty = bool(getattr(stream, "isatty", lambda: False)())
    colour = colour_mode == "always" or (colour_mode == "auto" and is_tty and "NO_COLOR" not in os.environ)
    unicode = unicode_mode == "always" or (unicode_mode == "auto" and is_tty and terminal_supports_unicode(stream))
    return colour, unicode
