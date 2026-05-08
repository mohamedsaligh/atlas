"""Runtime settings for the API. Loaded once at process start.

Settings come from (in priority order):
1. Constructor kwargs (used by tests).
2. Process environment, ``ATLAS_*`` prefix.
3. Defaults defined here.

The split keeps tests hermetic — pass an explicit ``Settings`` to
``create_app`` and the API never touches the user's environment.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API process settings. All field names map to ``ATLAS_<UPPER>``."""

    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # ── Storage ─────────────────────────────────────────────────────────────
    db_path: Path = Field(
        default=Path("~/.atlas/atlas.db"),
        description="Path to the SQLite snapshot. Opened read-only.",
    )

    # ── Server ──────────────────────────────────────────────────────────────
    api_prefix: str = Field(
        default="/api/v1",
        description="URL prefix for every routed endpoint.",
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed origins for CORS. Empty disables the middleware.",
    )

    # ── Auth (Phase 2.2) ────────────────────────────────────────────────────
    auth_mode: str = Field(
        default="disabled",
        description="One of: disabled | shared_secret | oidc.",
    )
    auth_shared_secret: str | None = Field(
        default=None,
        description="HS256 shared secret for the dev auth mode.",
    )
    auth_oidc_issuer: str | None = Field(
        default=None,
        description="OIDC issuer URL for production auth mode.",
    )
    auth_oidc_audience: str | None = Field(
        default=None,
        description="Required `aud` claim. Empty skips the audience check.",
    )

    # ── Observability ───────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        description="Root log level (DEBUG / INFO / WARNING / ERROR).",
    )
    log_format: str = Field(
        default="json",
        description="One of: json | console.",
    )
    metrics_enabled: bool = Field(
        default=True,
        description="Expose Prometheus /metrics.",
    )

    @property
    def resolved_db_path(self) -> Path:
        return Path(os.path.expanduser(str(self.db_path))).resolve()
