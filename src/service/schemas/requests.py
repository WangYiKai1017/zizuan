"""Pydantic models for API request/response bodies."""
import re
from typing import Optional

from pydantic import BaseModel, field_validator


class UserIdRequest(BaseModel):
    """Base request with user_id."""
    user_id: str
    
    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", v):
            raise ValueError("user_id must be 3-50 characters, alphanumeric and underscore only")
        return v


class InterviewMessageRequest(BaseModel):
    """Request body for sending a message in an interview session."""
    user_id: str
    session_id: str
    message: str
    
    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", v):
            raise ValueError("user_id must be 3-50 characters, alphanumeric and underscore only")
        return v
    
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
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", v):
            raise ValueError("user_id must be 3-50 characters, alphanumeric and underscore only")
        return v


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
