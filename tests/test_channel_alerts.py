"""Disaster / Bugs ingest and vendor classification helpers."""

from types import SimpleNamespace

import pytest

from slices.channel_alerts.classifier import (
    classification_gate,
    parse_classification,
    vendor_signals,
)
from slices.channel_alerts.models import Classification
from slices.channel_alerts.payload import normalize_payload, resolve_list
from slices.channel_alerts.service import ChannelAlertService
from slices.channel_alerts.settings_store import save_channel_alert_settings


def _settings():
    return SimpleNamespace(
        mattermost_disaster_channel_id="disaster-id",
        mattermost_bugs_channel_id="bugs-id",
        mattermost_disaster_channel_name="disaster",
        mattermost_bugs_channel_name="bugs",
    )


def test_resolve_list_by_channel_name():
    settings = _settings()
    assert resolve_list({"channel_name": "Disaster Channel"}, settings) == "disaster"
    assert resolve_list({"channel_name": "BUGs channel"}, settings) == "bugs"


def test_resolve_list_by_id_and_explicit_field():
    settings = _settings()
    assert resolve_list({"channel_id": "bugs-id", "channel_name": "random"}, settings) == "bugs"
    assert resolve_list({"list": "disaster", "channel_name": "BUGs"}, settings) == "disaster"


def test_resolve_list_unknown_channel():
    with pytest.raises(ValueError):
        resolve_list({"channel_name": "town-square", "text": "hello"}, _settings())


def test_normalize_mattermost_form():
    alert = normalize_payload(
        {
            "channel_name": "Disaster Channel",
            "channel_id": "disaster-id",
            "user_name": "ops",
            "post_id": "post-1",
            "text": "PSP timeout on checkout",
        },
        _settings(),
    )
    assert alert.external_id == "post-1"
    assert alert.list_name == "disaster"
    assert alert.user_name == "ops"
    assert "PSP" in alert.text


def test_parse_classification_fenced_json():
    parsed = parse_classification(
        '```json\n{"vendor_related": true, "vendor_name": "SnappPay", "reason": "PSP", "confidence": 0.82}\n```'
    )
    assert parsed["vendor_related"] is True
    assert parsed["vendor_name"] == "SnappPay"
    assert parsed["confidence"] == 0.82


def test_vendor_code_in_persian_message_is_not_blocked_by_empty_knowledge():
    text = (
        "وندور اعلام میکنند روزانه 10 بار از برنامه اردر خارج میشن "
        "و دوبار با کد تایید حتما باید وارد شوند ... کد وندور 5pl1ln"
    )
    signals = vendor_signals(text)
    assert signals["mentioned"] is True
    assert signals["codes"] == ["5pl1ln"]
    assert classification_gate(text, "") is None
    assert classification_gate("checkout timeout on payment-service", "") == "No matching vendor knowledge"


def test_parse_classification_rejects_prose():
    with pytest.raises(ValueError):
        parse_classification("this message is not about a vendor")


class _MemoryRepo:
    def __init__(self):
        self.saved = {}
        self.by_id = {}

    async def save_pending(self, incoming):
        from slices.channel_alerts.models import ChannelAlert

        current = self.saved.get(incoming.external_id)
        if current and current.text == incoming.text and current.classification_status == "done":
            return current
        alert = ChannelAlert(
            id=current.id if current else "alert-1",
            external_id=incoming.external_id,
            list_name=incoming.list_name,
            channel_id=incoming.channel_id,
            channel_name=incoming.channel_name,
            user_name=incoming.user_name,
            text=incoming.text,
            classification_status="pending",
        )
        self.saved[incoming.external_id] = alert
        self.by_id[alert.id] = alert
        return alert

    async def get(self, alert_id):
        return self.by_id.get(alert_id)

    async def apply_classification(self, alert_id, result: Classification):
        alert = self.by_id[alert_id]
        updated = alert.model_copy(
            update={
                "vendor_related": result.vendor_related and result.status == "done",
                "vendor_name": result.vendor_name if result.vendor_related else "",
                "vendor_reason": result.reason,
                "confidence": result.confidence,
                "classifier": result.classifier,
                "classification_status": result.status,
                "knowledge_hits": result.knowledge_hits,
            }
        )
        self.by_id[alert_id] = updated
        self.saved[updated.external_id] = updated
        return updated

    async def list_alerts(self, kind, limit=100):
        items = list(self.by_id.values())
        if kind == "vendor":
            return [item for item in items if item.vendor_related][:limit]
        return [item for item in items if item.list_name == kind][:limit]


@pytest.mark.asyncio
async def test_service_puts_vendor_message_on_vendor_list():
    repo = _MemoryRepo()

    async def classifier(text: str) -> Classification:
        related = "snapp" in text.lower()
        return Classification(
            vendor_related=related,
            vendor_name="SnappFood" if related else "",
            reason="Matched vendor knowledge" if related else "Internal only",
            confidence=0.9 if related else 0.1,
            classifier="ollama",
            knowledge_hits=["Vendors"],
            status="done",
        )

    service = ChannelAlertService(repo=repo, classifier=classifier)
    saved = await service.accept(
        {
            "list": "bugs",
            "post_id": "bug-9",
            "user_name": "qa",
            "text": "SnappFood callback failed",
        }
    )
    classified = await service.classify_saved(saved.id)
    vendor = await service.list_alerts("vendor")
    bugs = await service.list_alerts("bugs")
    assert classified is not None
    assert classified.vendor_related is True
    assert vendor[0].vendor_name == "SnappFood"
    assert bugs[0].list_name == "bugs"


def test_settings_switch_rejects_unknown_classifier(tmp_path, monkeypatch):
    import slices.channel_alerts.settings_store as store

    monkeypatch.setattr(store, "SETTINGS_PATH", tmp_path / "channel_alert_settings.json")
    save_channel_alert_settings("cursor_cli", "llama3.2:3b")
    loaded = store.get_channel_alert_settings()
    assert loaded.classifier == "cursor_cli"
    with pytest.raises(ValueError):
        save_channel_alert_settings("gpt", "llama3.2:3b")