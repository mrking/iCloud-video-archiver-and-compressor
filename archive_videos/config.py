"""Config loader and validator for archive-config.toml."""

from pathlib import Path
from typing import Literal

import toml
from pydantic import BaseModel, Field, field_validator


class S3Config(BaseModel):
    bucket: str = Field(..., description="S3 bucket name for Glacier uploads")
    region: str = Field(default="us-east-1", description="AWS region")
    prefix: str = Field(default="icloud-archiver/", description="S3 key prefix")
    storage_class: Literal["GLACIER", "DEEP_ARCHIVE"] = Field(
        default="DEEP_ARCHIVE",
        description="S3 storage class for uploaded originals",
    )


class CompressionConfig(BaseModel):
    codec: Literal["h264", "hevc"] = Field(default="hevc", description="Target codec")
    crf: int = Field(default=23, ge=0, le=51, description="Constant rate factor (0-51)")
    preset: Literal[
        "ultrafast", "superfast", "veryfast", "faster", "fast",
        "medium", "slow", "slower", "veryslow"
    ] = Field(default="medium", description="Encoding speed preset")
    max_height: int = Field(default=1080, ge=480, le=4320, description="Max output height")
    max_bitrate_mbps: float = Field(
        default=0.0, le=100.0,
        description="Max bitrate in Mbps; 0 or negative skips this cap (CRF controls quality only)",
    )
    audio_bitrate: str = Field(
        default="128k",
        description="Audio bitrate; 'copy' to preserve original audio",
    )

    @field_validator("crf")
    @classmethod
    def crf_range(cls, v: int) -> int:
        if v < 18:
            raise ValueError(
                "CRF below 18 produces extremely large files; use 18-28 for good quality."
            )
        return v


class FilterConfig(BaseModel):
    min_file_size_mb: float = Field(
        default=0.0,
        description="Only process videos larger than this (in MB). 0 = no size filter.",
    )
    min_bitrate_mbps: float = Field(
        default=0.0,
        description="Only process videos with bitrate above this (in Mbps). 0 = no bitrate filter.",
    )
    target_codecs: list[str] = Field(
        default=[],
        description="Only process videos with these codecs. Empty list = no codec filter.",
    )


class AppConfig(BaseModel):
    library_path: str | None = Field(
        default=None,
        description="Path to Photos library (None = system default)",
    )
    s3: S3Config
    compression: CompressionConfig
    filter: FilterConfig = Field(
        default_factory=FilterConfig,
        description="Discovery filter settings",
    )
    temp_dir: str = Field(default="/tmp/icloud-archiver", description="Temp working directory")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    dry_run: bool = Field(default=True, description="Dry-run by default")

    @field_validator("library_path")
    @classmethod
    def _empty_library_path_to_none(cls, v: str | None) -> str | None:
        if v == "":
            return None
        return v

    @field_validator("temp_dir")
    @classmethod
    def _ensure_temp_dir(cls, v: str) -> str:
        Path(v).mkdir(parents=True, exist_ok=True)
        return v


def load_config(path: str | Path) -> AppConfig:
    """Load and validate configuration from a TOML file."""
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = toml.loads(config_path.read_text(encoding="utf-8"))

    # Resolve library path default
    raw.setdefault("library_path", raw.get("library_path"))

    return AppConfig.model_validate(raw)


def resolve_config_path(cli_path: str | None = None) -> Path:
    """Resolve config path from CLI flag or standard locations."""
    candidates = [
        Path(cli_path) if cli_path else None,
        Path.home() / ".config" / "icloud-archiver" / "archive-config.toml",
        Path.home() / ".icloud-archiver" / "archive-config.toml",
        Path.cwd() / "archive-config.toml",
    ]
    for p in candidates:
        if p and p.exists():
            return p
    raise FileNotFoundError(
        "No archive-config.toml found. "
        "Provide --config or place at ~/.config/icloud-archiver/archive-config.toml"
    )
