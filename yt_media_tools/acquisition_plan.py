"""Backend-neutral physical metadata acquisition planning for yt-discover."""

from __future__ import annotations

from dataclasses import dataclass

from .source_capabilities import selected_facet_capabilities
from .source_model import SourceSpec

STAGE_ENUMERATE_IDENTITIES = "enumerate-identities"
STAGE_BASIC_METADATA = "basic-metadata"
STAGE_COMPLETE_METADATA = "complete-metadata"
STAGE_FORMATS = "formats"
STAGE_SUBTITLES = "subtitles"
STAGE_CHAPTERS = "chapters"
STAGE_THUMBNAILS = "thumbnails"
STAGE_TAGS = "tags"
STAGE_DYNAMIC_RAW = "dynamic-raw"

_STAGE_ORDER = (
    STAGE_ENUMERATE_IDENTITIES,
    STAGE_BASIC_METADATA,
    STAGE_COMPLETE_METADATA,
    STAGE_FORMATS,
    STAGE_SUBTITLES,
    STAGE_CHAPTERS,
    STAGE_THUMBNAILS,
    STAGE_TAGS,
    STAGE_DYNAMIC_RAW,
)

_COLLECTION_STAGE = {
    "formats": STAGE_FORMATS,
    "subtitles": STAGE_SUBTITLES,
    "automatic_captions": STAGE_SUBTITLES,
    "chapters": STAGE_CHAPTERS,
    "thumbnails": STAGE_THUMBNAILS,
    "tags": STAGE_TAGS,
}


@dataclass(frozen=True)
class AcquisitionStage:
    """One backend-neutral metadata acquisition stage."""

    name: str
    required: bool
    fields: frozenset[str]
    reason: str


@dataclass(frozen=True)
class PhysicalAcquisitionPlan:
    """Ordered metadata work required to satisfy one physical source boundary."""

    source: SourceSpec
    stages: tuple[AcquisitionStage, ...]
    reason: str

    @property
    def required_stages(self) -> tuple[AcquisitionStage, ...]:
        """Return required stages in stable execution order."""
        return tuple(stage for stage in self.stages if stage.required)

    @property
    def required_stage_names(self) -> tuple[str, ...]:
        """Return stable names of required stages."""
        return tuple(stage.name for stage in self.required_stages)

    @property
    def requires_detailed_metadata(self) -> bool:
        """Return whether any required stage needs complete per-entry extraction."""
        return any(
            stage.required
            and stage.name
            in {
                STAGE_COMPLETE_METADATA,
                STAGE_FORMATS,
                STAGE_SUBTITLES,
                STAGE_CHAPTERS,
                STAGE_THUMBNAILS,
                STAGE_TAGS,
                STAGE_DYNAMIC_RAW,
            }
            for stage in self.stages
        )

    def stage(self, name: str) -> AcquisitionStage:
        """Return one named stage, failing loudly for programmer mistakes."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)


def _collection_family(field: str) -> str | None:
    """Return the supported nested metadata collection family for one field."""
    if "." not in field:
        return None
    family = field.split(".", 1)[0].casefold()
    return family if family in _COLLECTION_STAGE else None


def _dynamic_raw(field: str) -> bool:
    """Return whether a field belongs to the open-ended raw metadata namespace."""
    return field.casefold().startswith("raw.")


def plan_physical_acquisition(
    *,
    source: SourceSpec,
    required_fields: frozenset[str],
    enumeration_fields: frozenset[str],
    detailed_fields: frozenset[str],
    skip: bool = False,
) -> PhysicalAcquisitionPlan:
    """Build an ordered backend-neutral acquisition plan from physical field needs.

    The plan describes semantic requirements only. It does not encode yt-dlp flags,
    YouTube.js calls, cache operations, or another backend's transport choices.
    """
    if skip:
        stages = tuple(
            AcquisitionStage(name, False, frozenset(), "the physical source boundary is proven empty")
            for name in _STAGE_ORDER
        )
        return PhysicalAcquisitionPlan(
            source,
            stages,
            "no metadata acquisition stages are required because the source boundary is proven empty",
        )

    facet = selected_facet_capabilities(source)
    collection_fields: dict[str, set[str]] = {name: set() for name in _COLLECTION_STAGE.values()}
    dynamic_fields: set[str] = set()
    ordinary_detailed: set[str] = set()

    for field in detailed_fields:
        family = _collection_family(field)
        if family is not None:
            collection_fields[_COLLECTION_STAGE[family]].add(field)
        elif _dynamic_raw(field):
            dynamic_fields.add(field)
        else:
            ordinary_detailed.add(field)

    identity_fields = frozenset(field for field in required_fields if field.casefold() in {"id", "source_index"})
    basic_fields = frozenset(enumeration_fields - identity_fields)

    stages: list[AcquisitionStage] = []
    stages.append(
        AcquisitionStage(
            STAGE_ENUMERATE_IDENTITIES,
            True,
            identity_fields,
            (
                "source identities are required to materialise candidate rows"
                if identity_fields
                else "source enumeration establishes the candidate relation even when no identity field is projected"
            ),
        )
    )
    stages.append(
        AcquisitionStage(
            STAGE_BASIC_METADATA,
            bool(basic_fields),
            basic_fields,
            (
                "authoritative lightweight fields are required: " + ", ".join(sorted(basic_fields))
                if basic_fields
                else "no additional authoritative lightweight fields are required"
            ),
        )
    )
    stages.append(
        AcquisitionStage(
            STAGE_COMPLETE_METADATA,
            bool(ordinary_detailed),
            frozenset(ordinary_detailed),
            (
                "complete entry metadata is required for: " + ", ".join(sorted(ordinary_detailed))
                if ordinary_detailed
                else "no ordinary complete-entry fields are required"
            ),
        )
    )

    for stage_name in (
        STAGE_FORMATS,
        STAGE_SUBTITLES,
        STAGE_CHAPTERS,
        STAGE_THUMBNAILS,
        STAGE_TAGS,
    ):
        fields = frozenset(collection_fields[stage_name])
        stages.append(
            AcquisitionStage(
                stage_name,
                bool(fields),
                fields,
                (
                    f"nested {stage_name} metadata is required for: " + ", ".join(sorted(fields))
                    if fields
                    else f"no nested {stage_name} metadata is required"
                ),
            )
        )

    stages.append(
        AcquisitionStage(
            STAGE_DYNAMIC_RAW,
            bool(dynamic_fields),
            frozenset(dynamic_fields),
            (
                "open-ended raw metadata is required for: " + ", ".join(sorted(dynamic_fields))
                if dynamic_fields
                else "no open-ended raw metadata is required"
            ),
        )
    )

    required_names = [stage.name for stage in stages if stage.required]
    adapter_note = (
        "the selected source can enumerate identities cheaply"
        if facet.cheaply_enumerates_identities
        else "the selected source does not promise a cheap identity-enumeration stage"
    )
    return PhysicalAcquisitionPlan(
        source,
        tuple(stages),
        "required stages: " + ", ".join(required_names) + f"; {adapter_note}",
    )
