import csv

import pytest

from src.config.initial_interview_questions import (
    INITIAL_INTERVIEW_QUESTIONS,
    QUESTION_DATA_PATH,
    load_initial_interview_questions,
)


def test_loads_guided_questions_from_csv():
    questions = load_initial_interview_questions()

    assert len(questions) == 62
    assert questions[0]["id"] == "q001"
    assert questions[0]["order"] == "1"
    assert questions[0]["stage"] == "childhood"
    assert questions[0]["stage_label"] == "童年与少年时光"
    assert "最早的记忆" in questions[0]["question"]
    assert set(questions[0]) == {"id", "order", "stage", "stage_label", "question"}
    assert questions[-1]["id"] == "q064"
    assert questions[-1]["stage"] == "middle_age"
    assert questions[-1]["stage_label"] == "中年深耕与转折"
    assert {question["id"] for question in questions}.isdisjoint({"q011", "q052"})
    assert next(q for q in questions if q["id"] == "q013")["question"].startswith(
        "以前条件都不富裕"
    )


def test_module_constant_uses_csv_data():
    assert INITIAL_INTERVIEW_QUESTIONS == load_initial_interview_questions()


def test_rejects_duplicate_question_ids(tmp_path):
    csv_path = tmp_path / "questions.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["id", "order", "stage", "stage_label", "question"],
        )
        writer.writeheader()
        writer.writerow({
            "id": "q001",
            "order": "1",
            "stage": "childhood",
            "stage_label": "童年",
            "question": "问题一",
        })
        writer.writerow({
            "id": "q001",
            "order": "2",
            "stage": "childhood",
            "stage_label": "童年",
            "question": "问题二",
        })

    with pytest.raises(ValueError, match="duplicate id"):
        load_initial_interview_questions(csv_path)


def test_question_csv_is_checked_in():
    assert QUESTION_DATA_PATH.exists()
