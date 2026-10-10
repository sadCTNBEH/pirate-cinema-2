"""Core domain and application exceptions."""

from backend.exceptions import (
    AppException,
    DatabaseError,
    ExternalServiceError,
    NotFoundError,
)

__all__ = [
    "AppException",
    "DatabaseError",
    "ExternalServiceError",
    "NotFoundError",
]
