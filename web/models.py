"""Typed request/response contracts shared by the Shorts Studio API.

Keeping the editor contract in one module prevents the web layer and the
renderer from slowly accepting different values.  The models intentionally
remain backwards compatible with persisted v0.9 projects while rejecting
values that the renderer cannot implement.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


Mode = Literal["local", "api"]
AspectRatio = Literal["9:16", "1:1", "4:5"]
DownloadFormat = Literal["360", "480", "720", "1080"]
CaptionStyle = Literal["clean", "bold", "boxed", "karaoke"]
CaptionPosition = Literal["top", "center", "bottom"]
Focus = Literal["balanced", "educational", "funny", "story", "controversial", "visual"]
FitMode = Literal["crop", "fit_blur"]
Layout = Literal["single", "split"]
WhisperModel = Literal["tiny", "base", "small", "medium", "large-v3"]
WhisperDevice = Literal["auto", "cpu", "cuda", "mps", "directml", "rocm"]
LLMProvider = Literal["openai", "gemini", "ollama"]

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")


def _clean_optional_path(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if "\x00" in cleaned or any(char in cleaned for char in "\r\n"):
        raise ValueError("path contains invalid characters")
    return cleaned[:2048]


class StrictModel(BaseModel):
    model_config = {"allow_inf_nan": False, "extra": "ignore"}


class CutRange(StrictModel):
    """One source interval kept in a multi-cut clip."""

    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> "CutRange":
        if self.end_time <= self.start_time + 0.1:
            raise ValueError("end_time must be at least 0.1s after start_time")
        return self


class JobRequest(StrictModel):
    url: str = Field(..., min_length=3, max_length=8192)
    mode: Mode = "local"
    num_clips: int = Field(3, ge=1, le=12)
    aspect_ratio: AspectRatio = "9:16"
    download_format: DownloadFormat = "720"
    language: Optional[str] = Field(default=None, max_length=16)
    caption_style: CaptionStyle = "bold"
    remove_silence: bool = False
    normalize_audio: bool = False
    denoise_audio: bool = False
    remove_filler_words: bool = False
    caption_position: CaptionPosition = "bottom"
    caption_font: str = Field("Arial", min_length=1, max_length=80)
    caption_size: int = Field(0, ge=0, le=120)
    caption_color: Optional[str] = None
    focus: Focus = "balanced"
    background_music: Optional[str] = None
    music_volume: float = Field(0.18, ge=0.0, le=1.0)
    music_fade_in: float = Field(0.0, ge=0.0, le=30.0)
    music_fade_out: float = Field(0.0, ge=0.0, le=30.0)
    watermark: Optional[str] = None
    auto_reframe: bool = True
    crop_position: float = Field(0.5, ge=0.0, le=1.0)
    fit_mode: FitMode = "crop"
    zoom: float = Field(1.0, ge=0.5, le=1.5)
    intro: Optional[str] = None
    outro: Optional[str] = None
    jump_cuts: bool = False
    layout: Layout = "single"
    whisper_model: Optional[WhisperModel] = None
    whisper_device: Optional[WhisperDevice] = None
    output_height: int = Field(1920, ge=0, le=4320)
    save_folder: Optional[str] = None
    llm_provider: Optional[LLMProvider] = None
    llm_model: Optional[str] = Field(default=None, max_length=120)
    llm_temperature: float = Field(0.2, ge=0.0, le=1.0)
    cuts: List[CutRange] = Field(default_factory=list, max_length=20)

    @field_validator("url", "caption_font", "llm_model", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return str(value).strip() if value is not None else value

    @field_validator("llm_model")
    @classmethod
    def validate_model_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        cleaned = str(value).strip()
        if not _MODEL_NAME.fullmatch(cleaned):
            raise ValueError("llm_model may contain only letters, numbers, dots, underscores, colons, slashes, and hyphens")
        return cleaned

    @field_validator("language", mode="before")
    @classmethod
    def clean_language(cls, value: object) -> Optional[str]:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or None

    @field_validator("caption_color")
    @classmethod
    def validate_color(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        cleaned = str(value).strip()
        if not _HEX_COLOR.fullmatch(cleaned):
            raise ValueError("caption_color must be a six-digit hex color")
        return cleaned.lower()

    @field_validator("background_music", "watermark", "intro", "outro", "save_folder")
    @classmethod
    def clean_paths(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_path(value)


class BatchRequest(JobRequest):
    url: str = ""
    urls: List[str] = Field(..., min_length=1, max_length=50)


class ClipUpdate(StrictModel):
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
    cuts: List[CutRange] = Field(default_factory=list, max_length=20)
    caption_style: Optional[CaptionStyle] = None
    caption_position: CaptionPosition = "bottom"
    caption_font: str = Field("Arial", min_length=1, max_length=80)
    caption_size: int = Field(0, ge=0, le=120)
    caption_color: Optional[str] = None
    crop_position: float = Field(0.5, ge=0.0, le=1.0)
    zoom: float = Field(1.0, ge=0.5, le=1.5)
    fit_mode: FitMode = "crop"
    layout: Layout = "single"
    output_height: int = Field(1920, ge=0, le=4320)
    music_volume: float = Field(0.18, ge=0.0, le=1.0)
    music_fade_in: float = Field(0.0, ge=0.0, le=30.0)
    music_fade_out: float = Field(0.0, ge=0.0, le=30.0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "ClipUpdate":
        if self.end_time <= self.start_time + 0.1:
            raise ValueError("end_time must be at least 0.1s after start_time")
        previous_end = -1.0
        for cut in self.cuts:
            if cut.start_time < previous_end:
                raise ValueError("cuts must be sorted and must not overlap")
            previous_end = cut.end_time
        return self

    @field_validator("caption_font", mode="before")
    @classmethod
    def strip_font(cls, value: object) -> str:
        return str(value or "Arial").strip()[:80] or "Arial"

    @field_validator("caption_color")
    @classmethod
    def validate_color(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        cleaned = str(value).strip()
        if not _HEX_COLOR.fullmatch(cleaned):
            raise ValueError("caption_color must be a six-digit hex color")
        return cleaned.lower()


class ProjectUpdate(StrictModel):
    name: str = Field(..., min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(str(value).split())
        if not cleaned:
            raise ValueError("project name cannot be blank")
        return cleaned


class OpenFolderRequest(StrictModel):
    job_id: Optional[str] = Field(default=None, max_length=64)


class SetupStateUpdate(StrictModel):
    dismissed: bool = True


class AuthLogin(StrictModel):
    token: str = Field(..., min_length=1, max_length=4096)


class CleanupRequest(StrictModel):
    confirm: bool = False
    older_than_days: int = Field(30, ge=1, le=3650)
    include_uploads: bool = False
    include_transcript_caches: bool = True
    include_model_cache: bool = False


class ProviderCostRates(StrictModel):
    """Creator-entered USD per million token rates; zero means unknown."""

    openai_input_usd_per_million: float = Field(0.0, ge=0.0, le=100000.0)
    openai_output_usd_per_million: float = Field(0.0, ge=0.0, le=100000.0)
    gemini_input_usd_per_million: float = Field(0.0, ge=0.0, le=100000.0)
    gemini_output_usd_per_million: float = Field(0.0, ge=0.0, le=100000.0)
    muapi_input_usd_per_million: float = Field(0.0, ge=0.0, le=100000.0)
    muapi_output_usd_per_million: float = Field(0.0, ge=0.0, le=100000.0)


class TranscriptWord(StrictModel):
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)
    word: str = Field(..., min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_order(self) -> "TranscriptWord":
        if self.end <= self.start:
            raise ValueError("word end must be after word start")
        return self


class TranscriptSegment(StrictModel):
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)
    text: str = Field(..., min_length=1, max_length=4000)
    words: List[TranscriptWord] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_order(self) -> "TranscriptSegment":
        if self.end <= self.start:
            raise ValueError("segment end must be after segment start")
        for word in self.words:
            if word.start < self.start - 0.001 or word.end > self.end + 0.001:
                raise ValueError("word timestamps must be inside their segment")
        return self


class TranscriptUpdate(StrictModel):
    segments: List[TranscriptSegment] = Field(..., min_length=1, max_length=5000)
    duration: Optional[float] = Field(default=None, ge=0, le=172800)

    @model_validator(mode="after")
    def validate_order(self) -> "TranscriptUpdate":
        previous_end = -1.0
        for segment in self.segments:
            if segment.start < previous_end:
                raise ValueError("transcript segments must be sorted and must not overlap")
            previous_end = segment.end
        if self.duration is not None and self.duration + 0.001 < self.segments[-1].end:
            raise ValueError("duration must cover the final segment")
        return self


class BrandPreset(StrictModel):
    name: str = Field(..., min_length=1, max_length=80)
    caption_style: CaptionStyle = "bold"
    caption_position: CaptionPosition = "bottom"
    caption_font: str = Field("Arial", min_length=1, max_length=80)
    caption_size: int = Field(0, ge=0, le=120)
    caption_color: Optional[str] = None
    watermark: Optional[str] = None
    intro: Optional[str] = None
    outro: Optional[str] = None
    background_music: Optional[str] = None
    music_volume: float = Field(0.18, ge=0, le=1)
    music_fade_in: float = Field(0, ge=0, le=30)
    music_fade_out: float = Field(0, ge=0, le=30)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(str(value).split())

    @field_validator("caption_color")
    @classmethod
    def validate_color(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        cleaned = str(value).strip()
        if not _HEX_COLOR.fullmatch(cleaned):
            raise ValueError("caption_color must be a six-digit hex color")
        return cleaned.lower()

    @field_validator("watermark", "intro", "outro", "background_music")
    @classmethod
    def clean_brand_paths(cls, value: Optional[str]) -> Optional[str]:
        return _clean_optional_path(value)


class PublishRequest(StrictModel):
    platform: Literal["youtube_shorts", "tiktok", "instagram_reels"]
    clip_index: Optional[int] = Field(default=None, ge=0, le=1000)


class RestoreRequest(StrictModel):
    confirm: bool = False
