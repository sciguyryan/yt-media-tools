"""JOIN integration with CTEs, UNION and relation-aware acquisition planning."""

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_source_boundaries
from yt_media_tools.query import apply_query, parse_query, query_physical_source_requests, resolve_query
from yt_media_tools.query_evaluator import canonical_record_value
from yt_media_tools.schema import QuerySchema
from yt_media_tools.sources import resolve_source_request


def _records():
    return [
        {"id": "a", "title": "Alpha", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "title": "Beta", "_yt_sql_source": "@left", "_yt_sql_source_facet": None},
        {"id": "b", "tag": "joined", "_yt_sql_source": "@right", "_yt_sql_source_facet": None},
        {"id": "c", "title": "Gamma", "_yt_sql_source": "@other", "_yt_sql_source_facet": None},
        {"id": "c", "tag": "union", "_yt_sql_source": "@tags", "_yt_sql_source_facet": None},
    ]


def _resolved(text):
    records = _records()
    requests = ("@left", "@right", "@other", "@tags")
    schemas = {(name, None): QuerySchema([r for r in records if r["_yt_sql_source"] == name]) for name in requests}
    return records, resolve_query(parse_query(text), QuerySchema(records), source_schemas=schemas)


def _project(rows, query):
    return [[canonical_record_value(row, term) for term in query.select] for row in rows]


def test_join_executes_inside_each_union_branch() -> None:
    records, query = _resolved(
        "SELECT l.id, r.tag FROM @left AS l JOIN @right AS r ON l.id = r.id "
        "UNION ALL SELECT o.id, t.tag FROM @other AS o JOIN @tags AS t ON o.id = t.id"
    )
    assert apply_query(records, query) == [{"id": "b", "tag": "joined"}, {"id": "c", "tag": "union"}]


def test_cte_produced_relation_is_consistent_join_input_to_union() -> None:
    records, query = _resolved(
        "WITH picked AS (SELECT id, tag FROM @right) "
        "SELECT l.id, p.tag FROM @left AS l LEFT JOIN picked AS p ON l.id = p.id "
        "UNION ALL SELECT o.id, t.tag FROM @other AS o JOIN @tags AS t ON o.id = t.id"
    )
    assert apply_query(records, query) == [
        {"id": "a", "tag": None},
        {"id": "b", "tag": "joined"},
        {"id": "c", "tag": "union"},
    ]


def test_acquisition_fields_are_attributed_to_owning_join_relation() -> None:
    query = parse_query(
        "SELECT l.title, r.duration FROM @left OF videos AS l JOIN @right OF videos AS r "
        "ON l.id = r.id WHERE r.view_count > 5"
    )
    requests = (("@left", "videos"), ("@right", "videos"))
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    plans = plan_source_boundaries(query, requests=requests, sources=sources, dates=DateContext())
    fields = {plan.source_name: plan.required_fields for plan in plans}
    assert fields["@left"] == frozenset({"id", "title"})
    assert fields["@right"] == frozenset({"id", "duration", "view_count"})


def test_false_inner_join_predicate_eliminates_both_acquisitions() -> None:
    query = parse_query("SELECT l.id FROM @left OF videos AS l JOIN @right OF videos AS r ON 1 = 0")
    requests = (("@left", "videos"), ("@right", "videos"))
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    plans = plan_source_boundaries(query, requests=requests, sources=sources, dates=DateContext())
    assert {plan.source_name: plan.acquisition.mode for plan in plans} == {"@left": "skip", "@right": "skip"}


def test_false_left_join_predicate_eliminates_only_joined_acquisition() -> None:
    query = parse_query("SELECT l.id FROM @left OF videos AS l LEFT JOIN @right OF videos AS r ON 1 = 0")
    requests = (("@left", "videos"), ("@right", "videos"))
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    plans = plan_source_boundaries(query, requests=requests, sources=sources, dates=DateContext())
    modes = {plan.source_name: plan.acquisition.mode for plan in plans}
    assert modes["@left"] != "skip"
    assert modes["@right"] == "skip"


def test_union_branch_join_inputs_participate_in_physical_acquisition_discovery() -> None:
    query = parse_query(
        "SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id "
        "UNION ALL SELECT o.id FROM @other AS o JOIN @tags AS t ON o.id = t.id"
    )
    assert query_physical_source_requests(query) == (
        ("@left", None),
        ("@right", None),
        ("@other", None),
        ("@tags", None),
    )


def test_contradictory_inner_join_predicate_eliminates_both_acquisitions() -> None:
    query = parse_query(
        "SELECT l.id FROM @left OF videos AS l JOIN @right OF videos AS r ON l.view_count = 5 AND l.view_count > 10"
    )
    requests = (("@left", "videos"), ("@right", "videos"))
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    plans = plan_source_boundaries(query, requests=requests, sources=sources, dates=DateContext())
    assert {plan.source_name: plan.acquisition.mode for plan in plans} == {"@left": "skip", "@right": "skip"}
    assert all(plan.elimination_proof is not None for plan in plans)
