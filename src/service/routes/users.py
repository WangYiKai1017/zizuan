"""User management routes — delete user and associated data."""

import logging
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.service.schemas.requests import USER_ID_PATTERN
from src.service.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_KB_BASE_PATH = _PROJECT_ROOT / "knowledge_base"


@router.delete("/{user_id}")
async def delete_user(user_id: str):
    """Delete a user and all associated data (knowledge base, sessions).

    Idempotent: returns 200 with status=not_found if user does not exist.
    """
    # Validate user_id format
    if not USER_ID_PATTERN.match(user_id):
        raise HTTPException(status_code=422, detail={
            "error": {
                "code": "INVALID_USER_ID",
                "message": "user_id must be 3-50 characters, alphanumeric and underscore only",
                "details": None,
            }
        })

    kb_path = _KB_BASE_PATH / user_id

    # Force-release any active sessions for this user
    session_manager = SessionManager.get_instance()
    released_count = await session_manager.force_release_all(user_id)
    if released_count > 0:
        logger.info("Force-released %d session(s) for user %s", released_count, user_id)

    # Delete knowledge base directory
    if not kb_path.exists():
        return JSONResponse(content={
            "status": "not_found",
            "user_id": user_id,
            "sessions_released": released_count,
        })

    try:
        shutil.rmtree(kb_path)
        logger.info("Deleted knowledge base for user %s: %s", user_id, kb_path)
    except OSError as e:
        logger.error("Failed to delete knowledge base for user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "DELETE_FAILED",
                "message": f"Failed to delete user data: {e}",
                "details": None,
            }
        })

    return JSONResponse(content={
        "status": "deleted",
        "user_id": user_id,
        "sessions_released": released_count,
    })
