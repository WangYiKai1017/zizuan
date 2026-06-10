"""Guided initial interview questions loaded from repo data."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List


QUESTION_DATA_PATH = (
    Path(__file__).resolve().parent / "data" / "initial_interview_questions.csv"
)
REQUIRED_COLUMNS = {"id", "order", "stage", "stage_label", "question", "focus"}
VALID_STAGES = {"childhood", "youth", "middle_age", "elderly"}


def load_initial_interview_questions(
    csv_path: str | Path = QUESTION_DATA_PATH,
) -> List[Dict[str, str]]:
    """Load the guided initial interview question table from CSV."""
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            raise ValueError(
                f"Initial interview question CSV missing columns: {sorted(missing)}"
            )

        questions: List[Dict[str, str]] = []
        seen_ids: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            question_id = (row.get("id") or "").strip()
            question = (row.get("question") or "").strip()
            stage = (row.get("stage") or "").strip()
            stage_label = (row.get("stage_label") or "").strip()
            order_text = (row.get("order") or "").strip()
            focus = (row.get("focus") or "").strip()

            if not question_id or not question:
                raise ValueError(
                    "Initial interview question CSV has empty id/question "
                    f"at row {row_number}"
                )
            if question_id in seen_ids:
                raise ValueError(
                    f"Initial interview question CSV has duplicate id: {question_id}"
                )
            seen_ids.add(question_id)
            if stage not in VALID_STAGES:
                raise ValueError(
                    f"Initial interview question CSV has invalid stage at row {row_number}: "
                    f"{stage}"
                )

            try:
                order = int(order_text)
            except ValueError as exc:
                raise ValueError(
                    "Initial interview question CSV has invalid order at row "
                    f"{row_number}: {order_text}"
                ) from exc

            questions.append(
                {
                    "id": question_id,
                    "order": str(order),
                    "stage": stage,
                    "stage_label": stage_label,
                    "question": question,
                    "focus": focus,
                }
            )

    return sorted(questions, key=lambda item: int(item["order"]))


INITIAL_INTERVIEW_QUESTIONS = load_initial_interview_questions()
