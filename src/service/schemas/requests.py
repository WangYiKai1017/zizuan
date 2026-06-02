"""Pydantic models for API request/response bodies."""
import re
from typing import List, Optional

from pydantic import BaseModel, field_validator


USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,50}$")


def validate_user_id_value(v: str) -> str:
    if not USER_ID_PATTERN.match(v):
        raise ValueError("user_id must be 3-50 characters, alphanumeric and underscore only")
    return v


class UserIdRequest(BaseModel):
    """Base request with user_id."""
    user_id: str
    
    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return validate_user_id_value(v)


class InterviewProfilePrefillRequest(BaseModel):
    """Profile fields obtained before starting an interview."""
    wechat_id: str
    user_id: str
    name: Optional[str] = None
    age: Optional[int] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None

    @field_validator("wechat_id")
    @classmethod
    def validate_wechat_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("wechat_id cannot be empty")
        if len(v) > 128:
            raise ValueError("wechat_id must be 128 characters or fewer")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_prefill_user_id(cls, v: str) -> str:
        return validate_user_id_value(v)

    @field_validator("name", "birth_date", "gender")
    @classmethod
    def strip_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        return v or None

    @field_validator("age")
    @classmethod
    def validate_age(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v <= 0 or v > 130:
            raise ValueError("age must be between 1 and 130")
        return v


class CandidateQuestion(BaseModel):
    """A prepared question from family members."""
    id: str
    question: str


class InterviewMessageRequest(BaseModel):
    """Request body for sending a message in an interview session."""
    user_id: str
    session_id: str
    message: str
    candidate_questions: Optional[List[CandidateQuestion]] = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return validate_user_id_value(v)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be empty")
        return v


class InterviewEndRequest(BaseModel):
    """Request body for ending an interview session."""
    user_id: str
    session_id: str
    
    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        return validate_user_id_value(v)


class ChapterConfirmRequest(BaseModel):
    """Optional request body for confirming a chapter."""
    notes: Optional[str] = None


class ErrorDetail(BaseModel):
    """Error detail structure."""
    code: str
    message: str
    details: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: ErrorDetail
