"""Pydantic schemas for the in-app updater."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UpdateCheckResponse(BaseModel):
    current_version: str = Field(description="Currently installed version")
    has_update: bool = Field(description="Whether a newer stable release is available")
    version: str = Field(description="Latest published stable release tag")
    release_notes: str = Field(default="", description="Release changelog / body")
    download_url: str = Field(default="", description="Direct download URL for the matched asset")
    release_url: str = Field(default="", description="HTML URL to view release on GitHub")
    asset_name: str = Field(default="", description="File name of the matched binary asset")
    size_bytes: int | None = Field(default=None, description="Asset file size in bytes")
    can_auto_update: bool = Field(default=False, description="Whether in-app auto-update can be performed")
    reason: str | None = Field(default=None, description="Explanation if auto-update is not supported")
    published_at: str | None = Field(default=None, description="ISO timestamp when release was published")
    sha256: str | None = Field(default=None, description="Expected SHA-256 checksum if available")


class UpdateStatusResponse(BaseModel):
    state: str = Field(
        default="idle",
        description="Current updater state: idle, checking, available, downloading, verifying, ready, applying, restarting, completed, failed, rolled_back",
    )
    version: str | None = Field(default=None, description="Target version being downloaded/applied")
    downloaded_bytes: int = Field(default=0, description="Bytes downloaded so far")
    total_bytes: int | None = Field(default=None, description="Total expected size in bytes")
    progress_percent: float = Field(default=0.0, description="Download progress percentage (0-100)")
    error: str | None = Field(default=None, description="Error message if operation failed")
    can_auto_update: bool = Field(default=False, description="Whether in-app auto-update is supported")
    asset_name: str | None = Field(default=None, description="Name of the asset file")


class UpdateActionResponse(BaseModel):
    status: str = Field(description="Action result status: success, started, applying, cancelled, etc.")
    message: str = Field(description="Human readable action result description")
