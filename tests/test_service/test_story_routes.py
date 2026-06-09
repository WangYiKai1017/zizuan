"""Tests for story service routes."""

import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.service.routes.stories import router


def _write_story(
    kb: Path,
    rel_path: str,
    title: str,
    life_stage_label: str,
    generated_at: str,
    event_paths: list[str],
) -> None:
    path = kb / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    source_lines = "\n".join(f"- {event_path}" for event_path in event_paths)
    path.write_text(
        f"""# {title}

> 生成时间：{generated_at}
> 来源时期：{life_stage_label}
> 来源事件数：{len(event_paths)}

这是故事正文。

<!--
source_events:
{source_lines}
-->
""",
        encoding="utf-8",
    )


def _client_for(kb: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_list_stories_filters_by_life_stage(tmp_path: Path) -> None:
    user_id = "user001"
    kb = tmp_path / user_id
    kb.mkdir()
    _write_story(
        kb,
        "stories/childhood_story_20260601_100000.md",
        "院子里的童年",
        "童年时期",
        "2026-06-01T10:00:00+08:00",
        ["events/childhood/a.md", "events/childhood/b.md"],
    )
    _write_story(
        kb,
        "stories/youth_story_20260602_100000.md",
        "远行之前",
        "青年时期",
        "2026-06-02T10:00:00+08:00",
        ["events/youth/a.md"],
    )
    (kb / "stories" / ".story_state.json").write_text(
        json.dumps(
            {
                "stories": [
                    {
                        "story_id": "childhood_story_20260601_100000",
                        "file_path": "stories/childhood_story_20260601_100000.md",
                        "life_stage": "childhood",
                        "event_paths": ["events/childhood/a.md", "events/childhood/b.md"],
                        "created_at": "2026-06-01T10:00:00+08:00",
                    },
                    {
                        "story_id": "youth_story_20260602_100000",
                        "file_path": "stories/youth_story_20260602_100000.md",
                        "life_stage": "youth",
                        "event_paths": ["events/youth/a.md"],
                        "created_at": "2026-06-02T10:00:00+08:00",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch("src.service.routes.stories._get_kb_path", return_value=str(kb)):
        response = _client_for(kb).get(f"/api/stories/{user_id}?life_stage=childhood")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user_id
    assert data["life_stage"] == "childhood"
    assert data["life_stage_label"] == "童年时期"
    assert data["count"] == 1
    assert data["stories"][0]["story_id"] == "childhood_story_20260601_100000"
    assert data["stories"][0]["story_path"] == "stories/childhood_story_20260601_100000.md"
    assert data["stories"][0]["title"] == "院子里的童年"
    assert data["stories"][0]["content"].startswith("# 院子里的童年")
    assert "source_events:" in data["stories"][0]["content"]
    assert data["stories"][0]["source_event_count"] == 2


def test_list_stories_returns_empty_when_no_stories_dir(tmp_path: Path) -> None:
    user_id = "user001"
    kb = tmp_path / user_id
    kb.mkdir()

    with patch("src.service.routes.stories._get_kb_path", return_value=str(kb)):
        response = _client_for(kb).get(f"/api/stories/{user_id}?life_stage=elderly")

    assert response.status_code == 200
    assert response.json()["stories"] == []
    assert response.json()["count"] == 0


def test_list_stories_rejects_invalid_life_stage(tmp_path: Path) -> None:
    user_id = "user001"
    kb = tmp_path / user_id
    kb.mkdir()

    with patch("src.service.routes.stories._get_kb_path", return_value=str(kb)):
        response = _client_for(kb).get(f"/api/stories/{user_id}?life_stage=unknown")

    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "INVALID_LIFE_STAGE"


def test_list_stories_returns_user_not_found(tmp_path: Path) -> None:
    user_id = "missing"
    kb = tmp_path / user_id

    with patch("src.service.routes.stories._get_kb_path", return_value=str(kb)):
        response = _client_for(kb).get(f"/api/stories/{user_id}?life_stage=childhood")

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "USER_NOT_FOUND"
