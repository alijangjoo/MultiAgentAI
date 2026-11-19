"""Lead-approved extra WIP. Navid never creates these by itself."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

STORE_PATH = Path("./data/navid_wip_exceptions.json")


class WipException(BaseModel):
    id: str
    person_id: str
    until: str
    reason: str = ""
    keys: list[str] = Field(default_factory=list)


def _read() -> list[WipException]:
    if not STORE_PATH.exists():
        return []
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    loaded: list[WipException] = []
    for item in items:
        try:
            loaded.append(WipException(**item))
        except Exception:
            continue
    return loaded


def _write(items: list[WipException]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": [item.model_dump() for item in items]}
    STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def list_exceptions() -> list[WipException]:
    return _read()


def add_exception(person_id: str, until: str, reason: str, keys: list[str]) -> WipException:
    person = (person_id or "").strip().lower()
    if person not in {"omid", "kambiz", "ali"}:
        raise ValueError("person_id must be omid, kambiz, or ali")
    try:
        date.fromisoformat(until)
    except ValueError as exc:
        raise ValueError("until must be YYYY-MM-DD") from exc
    cleaned = []
    for key in keys:
        text = str(key).strip().upper()
        if text and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("At least one issue key is required")
    item = WipException(
        id=str(uuid4()),
        person_id=person,
        until=until,
        reason=(reason or "").strip(),
        keys=cleaned,
    )
    items = _read()
    items.append(item)
    _write(items)
    return item


def delete_exception(exception_id: str) -> bool:
    items = _read()
    kept = [item for item in items if item.id != exception_id]
    if len(kept) == len(items):
        return False
    _write(kept)
    return True