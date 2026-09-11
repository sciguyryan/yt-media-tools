"""Backend-neutral metadata acquisition planning and yt-dlp lowering."""

from yt_media_tools.acquisition_plan import (
    STAGE_BASIC_METADATA,
    STAGE_CHAPTERS,
    STAGE_COMPLETE_METADATA,
    STAGE_DYNAMIC_RAW,
    STAGE_ENUMERATE_IDENTITIES,
    STAGE_FORMATS,
    STAGE_SUBTITLES,
    STAGE_THUMBNAILS,
    plan_physical_acquisition,
)
from yt_media_tools.dates import DateContext
from yt_media_tools.discover_explain import explain_user_query, explain_user_query_json
from yt_media_tools.planner import plan_query, plan_source_boundaries
from yt_media_tools.query import parse_query, query_physical_source_requests
from yt_media_tools.sources import resolve_source_request
from yt_media_tools.ytdlp import lower_acquisition_plan_to_ytdlp


def _source(name: str = "@example"):
    return resolve_source_request(name, facet="videos")


def test_identity_only_query_requires_only_identity_enumeration() -> None:
    query = parse_query("SELECT id FROM @example OF videos")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.physical_acquisition.required_stage_names == (STAGE_ENUMERATE_IDENTITIES,)
    assert not plan.physical_acquisition.requires_detailed_metadata


def test_exact_flat_field_adds_basic_metadata_stage() -> None:
    query = parse_query("SELECT id, title FROM @example OF videos")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.physical_acquisition.required_stage_names == (
        STAGE_ENUMERATE_IDENTITIES,
        STAGE_BASIC_METADATA,
    )
    assert plan.physical_acquisition.stage(STAGE_BASIC_METADATA).fields == frozenset({"title"})


def test_ordinary_detailed_field_adds_complete_metadata_stage() -> None:
    query = parse_query("SELECT id, duration FROM @example OF videos")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.physical_acquisition.required_stage_names == (
        STAGE_ENUMERATE_IDENTITIES,
        STAGE_COMPLETE_METADATA,
    )
    assert plan.physical_acquisition.stage(STAGE_COMPLETE_METADATA).fields == frozenset({"duration"})
    assert plan.physical_acquisition.requires_detailed_metadata


def test_nested_and_dynamic_fields_get_distinct_semantic_stages() -> None:
    plan = plan_physical_acquisition(
        source=_source(),
        required_fields=frozenset(
            {
                "id",
                "formats.video_ext",
                "chapters.title",
                "subtitles.en",
                "automatic_captions.en",
                "thumbnails.url",
                "raw.extra.score",
            }
        ),
        enumeration_fields=frozenset({"id"}),
        detailed_fields=frozenset(
            {
                "formats.video_ext",
                "chapters.title",
                "subtitles.en",
                "automatic_captions.en",
                "thumbnails.url",
                "raw.extra.score",
            }
        ),
    )

    assert plan.required_stage_names == (
        STAGE_ENUMERATE_IDENTITIES,
        STAGE_FORMATS,
        STAGE_SUBTITLES,
        STAGE_CHAPTERS,
        STAGE_THUMBNAILS,
        STAGE_DYNAMIC_RAW,
    )
    assert plan.stage(STAGE_SUBTITLES).fields == frozenset({"subtitles.en", "automatic_captions.en"})


def test_empty_source_boundary_has_no_required_acquisition_stages() -> None:
    query = parse_query("SELECT id FROM @example OF videos WHERE view_count >= 10 AND view_count < 10")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.source_branch_eliminated
    assert plan.physical_acquisition.required_stage_names == ()
    assert not plan.physical_acquisition.requires_detailed_metadata


def test_union_boundaries_keep_independent_acquisition_stage_plans() -> None:
    query = parse_query("SELECT title FROM @alpha UNION ALL SELECT duration FROM @beta")
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    boundaries = plan_source_boundaries(
        query,
        requests=requests,
        sources=sources,
        dates=DateContext(),
    )

    alpha = next(branch for branch in boundaries if branch.source_name == "@alpha")
    beta = next(branch for branch in boundaries if branch.source_name == "@beta")
    assert STAGE_BASIC_METADATA in alpha.physical_acquisition.required_stage_names
    assert STAGE_COMPLETE_METADATA not in alpha.physical_acquisition.required_stage_names
    assert STAGE_COMPLETE_METADATA in beta.physical_acquisition.required_stage_names


def test_ytdlp_lowering_keeps_semantic_collection_stages_visible() -> None:
    plan = plan_physical_acquisition(
        source=_source(),
        required_fields=frozenset({"id", "formats.video_ext", "raw.extra.score"}),
        enumeration_fields=frozenset({"id"}),
        detailed_fields=frozenset({"formats.video_ext", "raw.extra.score"}),
    )
    lowering = lower_acquisition_plan_to_ytdlp(plan)

    assert lowering.flat_stages == (STAGE_ENUMERATE_IDENTITIES,)
    assert lowering.detailed_stages == (STAGE_FORMATS, STAGE_DYNAMIC_RAW)
    assert lowering.collapsed_detailed_stages == (
        STAGE_FORMATS,
        STAGE_DYNAMIC_RAW,
    )
    assert lowering.requires_flat_enumeration
    assert lowering.requires_detailed_extraction


def test_ytdlp_lowering_of_empty_plan_requires_no_backend_work() -> None:
    plan = plan_physical_acquisition(
        source=_source(),
        required_fields=frozenset(),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset(),
        skip=True,
    )
    lowering = lower_acquisition_plan_to_ytdlp(plan)

    assert lowering.flat_stages == ()
    assert lowering.detailed_stages == ()
    assert not lowering.requires_flat_enumeration
    assert not lowering.requires_detailed_extraction


def test_human_explain_lists_backend_neutral_acquisition_stages() -> None:
    output = explain_user_query(
        "SELECT id, title, duration FROM @example",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )

    assert "Metadata acquisition stages" in output
    assert "enumerate-identities: required" in output
    assert "basic-metadata: required" in output
    assert "complete-metadata: required" in output
    assert "yt-dlp lowering:" in output


def test_json_explain_exposes_stages_and_ytdlp_lowering() -> None:
    payload = explain_user_query_json(
        "SELECT id, duration FROM @example",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )
    boundary = payload["source_boundaries"][0]

    assert boundary["required_acquisition_stages"] == [
        STAGE_ENUMERATE_IDENTITIES,
        STAGE_COMPLETE_METADATA,
    ]
    assert boundary["ytdlp_lowering"]["flat_stages"] == [
        STAGE_ENUMERATE_IDENTITIES,
    ]
    assert boundary["ytdlp_lowering"]["detailed_stages"] == [
        STAGE_COMPLETE_METADATA,
    ]
