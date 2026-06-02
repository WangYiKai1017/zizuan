"""Tests for WeChat profile prefill route."""

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_prefill_profile_writes_user_md_and_returns_mapping(tmp_path: Path) -> None:
    from src.service.routes.interview import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    with patch("src.service.routes.interview._knowledge_base_root", return_value=tmp_path):
        response = client.post(
            "/api/interview/profile/prefill",
            json={
                "wechat_id": "wx_openid_abc",
                "user_id": "test_user002",
                "name": "王秀兰",
                "age": 78,
                "birth_date": "1948-01-02",
                "gender": "female",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test_user002"
    assert data["wechat_id"] == "wx_openid_abc"
    assert data["profile"]["name"] == "王秀兰"
    assert data["profile"]["gender"] == "女"
    assert data["profile"]["birth_year"] == "1948"
    assert data["profile_complete"] is False
    assert "occupation" in data["missing_required_fields"]

    user_md = tmp_path / "test_user002" / "user.md"
    content = user_md.read_text(encoding="utf-8")
    assert "- 微信ID: wx_openid_abc" in content
    assert "- 姓名: 王秀兰" in content
    assert "- 年龄: 78" in content
    assert "- 性别: 女" in content
    assert "- 出生日期: 1948-01-02" in content
