"""Pydantic schemas for the Diagnostics & Health endpoint."""

from datetime import datetime
from pydantic import BaseModel, Field


class TorrServerDiagnostics(BaseModel):
    running: bool
    port: int | None = None
    pid: int | None = None
    last_error: str | None = None


class MPVDiagnostics(BaseModel):
    available: bool
    path: str | None = None
    version: str | None = None


class DiskDiagnostics(BaseModel):
    data_dir: str
    used_mb: float | None = None
    free_mb: float | None = None


class DatabaseDiagnostics(BaseModel):
    ok: bool
    size_mb: float | None = None


class DiagnosticError(BaseModel):
    timestamp: datetime
    component: str
    error_type: str
    message: str


class DiagnosticsResponse(BaseModel):
    version: str
    status: str = Field(
        default="healthy",
        description="Overall system status: healthy, degraded, or unhealthy",
    )
    checked_at: datetime = Field(
        description="ISO timestamp of when diagnostics were collected"
    )
    response_time_ms: float = Field(
        description="Total diagnostic collection time in milliseconds"
    )
    torrserver: TorrServerDiagnostics
    mpv: MPVDiagnostics
    disk: DiskDiagnostics
    db: DatabaseDiagnostics
    last_errors: list[DiagnosticError] = Field(default_factory=list)
