"""Deterministic chapter identity matching for biography outline workflows."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from src.models.biography_models import ChapterEntry, ChapterStatus


def normalize_identity_text(value: str) -> str:
    """Normalize a human-facing label without translating its meaning."""
    return re.sub(r"[\W_]+", "", (value or "").lower(), flags=re.UNICODE)


def narrative_materials(chapter: ChapterEntry) -> set[str]:
    """Return story-bearing sources, excluding commonly shared person files."""
    materials = set(chapter.source_materials or [])
    narrative = {
        path for path in materials
        if path.startswith(("events/", "timeline/", "themes/"))
    }
    return narrative or materials


def chapter_identity_reason(
    existing: ChapterEntry,
    proposed: ChapterEntry,
    *,
    include_id: bool = True,
) -> str | None:
    """Return a strong reason that two entries represent one chapter."""
    if include_id and existing.id == proposed.id:
        return "same_id"
    if existing.life_stage != proposed.life_stage:
        return None

    existing_title = normalize_identity_text(existing.title)
    proposed_title = normalize_identity_text(proposed.title)
    existing_theme = normalize_identity_text(existing.theme)
    proposed_theme = normalize_identity_text(proposed.theme)
    existing_materials = narrative_materials(existing)
    proposed_materials = narrative_materials(proposed)

    title_same = bool(existing_title and existing_title == proposed_title)
    theme_same = bool(existing_theme and existing_theme == proposed_theme)
    materials_same = bool(
        existing_materials
        and existing_materials == proposed_materials
    )

    if title_same and (
        theme_same
        or materials_same
        or not existing_materials
        or not proposed_materials
    ):
        return "same_title"
    if theme_same and materials_same:
        return "same_theme_and_materials"

    if not (theme_same and existing_materials and proposed_materials):
        return None
    overlap = len(existing_materials & proposed_materials) / len(
        existing_materials | proposed_materials
    )
    title_similarity = SequenceMatcher(
        None,
        existing_title,
        proposed_title,
    ).ratio()
    if overlap >= 0.8 and title_similarity >= 0.72:
        return "same_theme_and_overlapping_materials"
    return None


def status_rank(status: ChapterStatus) -> int:
    """Prefer chapters with user confirmation or completed writing."""
    return {
        ChapterStatus.DRAFT: 1,
        ChapterStatus.CONFIRMED: 2,
        ChapterStatus.OUTDATED: 3,
        ChapterStatus.WRITTEN: 4,
    }[status]


def deduplicate_chapters(
    chapters: list[ChapterEntry],
    *,
    match_by_id: bool = True,
) -> tuple[list[ChapterEntry], list[tuple[ChapterEntry, ChapterEntry, str]]]:
    """Keep the most mature chapter for each deterministic identity match."""
    unique: list[ChapterEntry] = []
    removed: list[tuple[ChapterEntry, ChapterEntry, str]] = []
    for chapter in chapters:
        match_index = None
        match_reason = None
        for index, candidate in enumerate(unique):
            reason = chapter_identity_reason(
                candidate,
                chapter,
                include_id=match_by_id,
            )
            if reason:
                match_index = index
                match_reason = reason
                break
        if match_index is None:
            unique.append(chapter)
            continue

        current = unique[match_index]
        if status_rank(chapter.status) > status_rank(current.status):
            unique[match_index] = chapter
            removed.append((current, chapter, match_reason or "duplicate"))
        else:
            removed.append((chapter, current, match_reason or "duplicate"))
    return unique, removed
