"""Classifier switch persisted for the Disaster & Bugs dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import get_settings

SETTINGS_PATH = Path("./data/channel_alert_settings.json")

CLASSIFIERS = ("ollama", "cursor_cli")
OLLAMA_MODELS = (
    "llama3.2:3b",
    "gemma3:1b",
    "starcoder2:7b",
    "deepseek-coder:6.7b",
    "codellama:7b",
)


class ChannelAlertSettings(BaseModel):
    classifier: str = "ollama"
    ollama_model: str = "llama3.2:3b"
    ollama_models: list[str] = Field(default_factory=lambda: list(OLLAMA_MODELS))


def _defaults() -> ChannelAlertSettings:
    settings = get_settings()
    classifier = (settings.incident_classifier or "ollama").strip().lower()
    if classifier not in CLASSIFIERS:
        classifier = "ollama"
    model = (settings.ollama_classifier_model or "llama3.2:3b").strip() or "llama3.2:3b"
    return ChannelAlertSettings(classifier=classifier, ollama_model=model)


def get_channel_alert_settings() -> ChannelAlertSettings:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            classifier = str(data.get("classifier") or "ollama").strip().lower()
            if classifier not in CLASSIFIERS:
                classifier = "ollama"
            model = str(data.get("ollama_model") or "llama3.2:3b").strip() or "llama3.2:3b"
            return ChannelAlertSettings(classifier=classifier, ollama_model=model)
        except Exception:
            pass
    return _defaults()


def save_channel_alert_settings(classifier: str, ollama_model: str) -> ChannelAlertSettings:
    mode = (classifier or "").strip().lower()
    if mode not in CLASSIFIERS:
        raise ValueError("classifier must be ollama or cursor_cli")
    model = (ollama_model or "").strip() or "llama3.2:3b"
    saved = ChannelAlertSettings(classifier=mode, ollama_model=model)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"classifier": saved.classifier, "ollama_model": saved.ollama_model}, indent=2),
        encoding="utf-8",
    )
    return saved