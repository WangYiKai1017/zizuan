"""Tests for file service routes."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def kb_structure(tmp_path: Path) -> Path:
    """Create a temporary knowledge base directory structure."""
    user_dir = tmp_path / "test_user001"
    user_dir.mkdir()

    # events/childhood/出生.md
    childhood_dir = user_dir / "events" / "childhood"
    childhood_dir.mkdir(parents=True)
    birth_file = childhood_dir / "出生.md"
    birth_file.write_text("# 出生\n\n1940年出生于北京。", encoding="utf-8")

    # events/youth/ (empty dir)
    (user_dir / "events" / "youth").mkdir(parents=True)

    # people/family/父亲.md
    family_dir = user_dir / "people" / "family"
    family_dir.mkdir(parents=True)
    father_file = family_dir / "父亲.md"
    father_file.write_text("# 父亲\n\n父亲是一位教师。", encoding="utf-8")

    # timeline/life-events.md
    timeline_dir = user_dir / "timeline"
    timeline_dir.mkdir()
    timeline_file = timeline_dir / "life-events.md"
    timeline_file.write_text("# 人生大事\n\n- 1940 出生", encoding="utf-8")

    # index.md at root
    index_file = user_dir / "index.md"
    index_file.write_text("# test_user001 知识库\n\n用户索引文件。", encoding="utf-8")

    # A JSON file for content_type testing
    conv_file = user_dir / "conversation.json"
    conv_file.write_text('{"messages": []}', encoding="utf-8")

    return tmp_path


@pytest.fixture
def test_app(kb_structure: Path) -> TestClient:
    """Create a test app with the temporary knowledge base."""
    with patch(
        "src.service.routes.files.KB_BASE_PATH", kb_structure
    ):
        from src.service.routes.files import router

        app = FastAPI()
        app.include_router(router, prefix="/api")
        client = TestClient(app)
        yield client


class TestListRootDirectory:
    """Tests for GET /api/files/{user_id}."""

    def test_list_root_directory(self, test_app: TestClient) -> None:
        """Verify items list with correct types and sizes."""
        response = test_app.get("/api/files/test_user001")
        assert response.status_code == 200

        data = response.json()
        assert data["user_id"] == "test_user001"
        assert "base_path" in data
        assert "items" in data

        items = data["items"]
        names = [item["name"] for item in items]

        # Directories should be present
        assert "events" in names
        assert "people" in names
        assert "timeline" in names

        # Files should be present
        assert "index.md" in names
        assert "conversation.json" in names

        # Check directory item format
        events_item = next(i for i in items if i["name"] == "events")
        assert events_item["type"] == "directory"
        assert events_item["path"] == "events/"

        # Check file item format
        index_item = next(i for i in items if i["name"] == "index.md")
        assert index_item["type"] == "file"
        assert index_item["path"] == "index.md"
        assert "size" in index_item
        assert index_item["size"] > 0
        assert "last_modified" in index_item


class TestListSubdirectory:
    """Tests for GET /api/files/{user_id}/{path:path} on directories."""

    def test_list_subdirectory(self, test_app: TestClient) -> None:
        """GET /api/files/user/events/childhood/ returns directory listing."""
        response = test_app.get("/api/files/test_user001/events/childhood")
        assert response.status_code == 200

        data = response.json()
        assert data["user_id"] == "test_user001"
        assert data["type"] == "directory"
        assert data["path"] == "events/childhood"

        items = data["items"]
        assert len(items) == 1
        assert items[0]["name"] == "出生.md"
        assert items[0]["type"] == "file"

    def test_directory_via_path(self, test_app: TestClient) -> None:
        """Accessing a directory via the path endpoint returns items."""
        response = test_app.get("/api/files/test_user001/events")
        assert response.status_code == 200

        data = response.json()
        assert data["type"] == "directory"
        names = [item["name"] for item in data["items"]]
        assert "childhood" in names
        assert "youth" in names


class TestGetFileContent:
    """Tests for GET /api/files/{user_id}/{path:path} on files."""

    def test_get_file_content(self, test_app: TestClient) -> None:
        """GET /api/files/user/events/childhood/出生.md returns file content."""
        response = test_app.get("/api/files/test_user001/events/childhood/出生.md")
        assert response.status_code == 200

        data = response.json()
        assert data["user_id"] == "test_user001"
        assert data["filename"] == "出生.md"
        assert data["path"] == "events/childhood/出生.md"
        assert data["content_type"] == "text/markdown"
        assert "# 出生" in data["content"]
        assert "1940年出生于北京" in data["content"]
        assert "size" in data
        assert "last_modified" in data

    def test_get_json_file_content_type(self, test_app: TestClient) -> None:
        """JSON files should have application/json content_type."""
        response = test_app.get("/api/files/test_user001/conversation.json")
        assert response.status_code == 200

        data = response.json()
        assert data["content_type"] == "application/json"
        assert data["content"] == '{"messages": []}'


class TestGetTree:
    """Tests for GET /api/files/{user_id}/tree."""

    def test_get_tree(self, test_app: TestClient) -> None:
        """Verify recursive tree structure."""
        response = test_app.get("/api/files/test_user001/tree")
        assert response.status_code == 200

        data = response.json()
        assert data["user_id"] == "test_user001"
        assert "tree" in data

        tree = data["tree"]
        assert tree["name"] == "test_user001"
        assert tree["type"] == "directory"
        assert "children" in tree

        # Find events in children
        children_names = [c["name"] for c in tree["children"]]
        assert "events" in children_names
        assert "people" in children_names
        assert "timeline" in children_names
        assert "index.md" in children_names

        # Check nested structure
        events = next(c for c in tree["children"] if c["name"] == "events")
        assert events["type"] == "directory"
        event_children_names = [c["name"] for c in events["children"]]
        assert "childhood" in event_children_names

        # Check file node in tree
        index_node = next(c for c in tree["children"] if c["name"] == "index.md")
        assert index_node["type"] == "file"
        assert "size" in index_node
        assert "path" in index_node


class TestErrorHandling:
    """Tests for error responses."""

    def test_user_not_found(self, test_app: TestClient) -> None:
        """404 response when user directory doesn't exist."""
        response = test_app.get("/api/files/nonexistent_user")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data["detail"]
        assert data["detail"]["error"]["code"] == "USER_NOT_FOUND"

    def test_file_not_found(self, test_app: TestClient) -> None:
        """404 response when file path doesn't exist."""
        response = test_app.get("/api/files/test_user001/nonexistent.md")
        assert response.status_code == 404

        data = response.json()
        assert "error" in data["detail"]
        assert data["detail"]["error"]["code"] == "FILE_NOT_FOUND"

    def test_path_traversal_blocked(self, test_app: TestClient) -> None:
        """Paths with '..' are rejected by the check function."""
        from fastapi import HTTPException as _HTTPException

        from src.service.routes.files import _check_path_traversal

        with pytest.raises(_HTTPException) as exc_info:
            _check_path_traversal("../../../etc/passwd")
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["error"]["code"] == "FILE_NOT_FOUND"

    def test_path_traversal_middle(self, test_app: TestClient) -> None:
        """Paths with '..' in the middle are rejected."""
        from fastapi import HTTPException as _HTTPException

        from src.service.routes.files import _check_path_traversal

        with pytest.raises(_HTTPException) as exc_info:
            _check_path_traversal("events/../../secrets")
        assert exc_info.value.status_code == 404

    def test_user_not_found_tree(self, test_app: TestClient) -> None:
        """Tree endpoint also returns 404 for missing user."""
        response = test_app.get("/api/files/nonexistent_user/tree")
        assert response.status_code == 404
