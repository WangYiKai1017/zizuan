"""File service routes — read-only access to user knowledge base directories."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/files", tags=["files"])

# Determine project root: src/service/routes/files.py → project root (4 levels up)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Knowledge base path from environment variable, default "knowledge_base"
_KB_RELATIVE = os.environ.get("KNOWLEDGE_BASE_PATH", "knowledge_base")
KB_BASE_PATH = _PROJECT_ROOT / _KB_RELATIVE


def _get_content_type(filename: str) -> str:
    """Determine content type based on file extension."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    elif suffix == ".json":
        return "application/json"
    elif suffix in (".yaml", ".yml"):
        return "text/yaml"
    else:
        return "text/plain"


# Binary file extensions → MIME types (served as raw file download, not JSON-wrapped text)
_BINARY_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
}


def _is_binary_file(filename: str) -> bool:
    """Check if a file should be served as binary (not read as text)."""
    return Path(filename).suffix.lower() in _BINARY_MIME_TYPES


def _check_path_traversal(path: str) -> None:
    """Reject paths containing '..' to prevent path traversal attacks."""
    if ".." in path.split("/") or ".." in path.split(os.sep):
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "FILE_NOT_FOUND", "message": "Invalid path."}},
        )


def _get_user_dir(user_id: str) -> Path:
    """Get and validate user directory path."""
    user_dir = KB_BASE_PATH / user_id
    if not user_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "USER_NOT_FOUND",
                    "message": f"User directory not found: {user_id}",
                }
            },
        )
    return user_dir


def _build_item(entry: Path, base_dir: Path) -> dict[str, Any]:
    """Build an item dict for a directory entry."""
    relative = entry.relative_to(base_dir)
    if entry.is_dir():
        return {
            "name": entry.name,
            "path": str(relative) + "/",
            "type": "directory",
        }
    else:
        stat = entry.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        return {
            "name": entry.name,
            "path": str(relative),
            "type": "file",
            "size": stat.st_size,
            "last_modified": mtime.isoformat(),
        }


def _build_tree(directory: Path) -> dict[str, Any]:
    """Recursively build a directory tree."""
    node: dict[str, Any] = {
        "name": directory.name,
        "type": "directory",
        "children": [],
    }
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return node

    for entry in entries:
        if entry.is_dir():
            node["children"].append(_build_tree(entry))
        else:
            stat = entry.stat()
            # path relative to user root
            node["children"].append(
                {
                    "name": entry.name,
                    "type": "file",
                    "size": stat.st_size,
                    "path": entry.name,
                }
            )
    return node


def _build_tree_with_paths(directory: Path, user_root: Path) -> dict[str, Any]:
    """Recursively build a directory tree with relative paths from user root."""
    node: dict[str, Any] = {
        "name": directory.name,
        "type": "directory",
        "children": [],
    }
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return node

    for entry in entries:
        if entry.is_dir():
            node["children"].append(_build_tree_with_paths(entry, user_root))
        else:
            stat = entry.stat()
            rel_path = str(entry.relative_to(user_root))
            node["children"].append(
                {
                    "name": entry.name,
                    "type": "file",
                    "size": stat.st_size,
                    "path": rel_path,
                }
            )
    return node


@router.get("/{user_id}")
async def list_root_directory(user_id: str) -> dict[str, Any]:
    """List root directory of a user's knowledge base (one level only)."""
    user_dir = _get_user_dir(user_id)

    items = []
    entries = sorted(user_dir.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        items.append(_build_item(entry, user_dir))

    return {
        "user_id": user_id,
        "base_path": f"{_KB_RELATIVE}/{user_id}/",
        "items": items,
    }


@router.get("/{user_id}/tree")
async def get_directory_tree(user_id: str) -> dict[str, Any]:
    """Get recursive directory tree for a user's knowledge base."""
    user_dir = _get_user_dir(user_id)
    tree = _build_tree_with_paths(user_dir, user_dir)
    return {
        "user_id": user_id,
        "tree": tree,
    }


@router.get("/{user_id}/{path:path}")
async def get_file_or_directory(user_id: str, path: str) -> dict[str, Any]:
    """Get file content or subdirectory listing."""
    _check_path_traversal(path)
    user_dir = _get_user_dir(user_id)

    target = user_dir / path
    # Resolve and ensure it's still within user_dir
    try:
        resolved = target.resolve()
        user_resolved = user_dir.resolve()
        if not str(resolved).startswith(str(user_resolved)):
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "FILE_NOT_FOUND",
                        "message": "Invalid path.",
                    }
                },
            )
    except (OSError, ValueError):
        raise HTTPException(
            status_code=404,
            detail={
                "error": {"code": "FILE_NOT_FOUND", "message": "Invalid path."}
            },
        )

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "FILE_NOT_FOUND",
                    "message": f"Path not found: {path}",
                }
            },
        )

    if target.is_dir():
        items = []
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        for entry in entries:
            items.append(_build_item(entry, user_dir))
        return {
            "user_id": user_id,
            "path": path,
            "type": "directory",
            "items": items,
        }
    else:
        # Binary files → serve raw via FileResponse (images, audio, etc.)
        suffix = target.suffix.lower()
        if suffix in _BINARY_MIME_TYPES:
            return FileResponse(
                path=str(target),
                media_type=_BINARY_MIME_TYPES[suffix],
                filename=target.name,
            )

        # Text files → JSON-wrapped content
        stat = target.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        content = target.read_text(encoding="utf-8")
        return {
            "user_id": user_id,
            "filename": target.name,
            "path": path,
            "size": stat.st_size,
            "last_modified": mtime.isoformat(),
            "content_type": _get_content_type(target.name),
            "content": content,
        }
