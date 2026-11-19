"""Vendor classification from Knowledge excerpts via Ollama or Cursor CLI."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from core.config import get_settings
from slices.channel_alerts.models import Classification
from slices.channel_alerts.settings_store import get_channel_alert_settings

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_VENDOR_WORD = re.compile(r"وندور|فروشنده|تامین‌کننده|تامین کننده|vendor|supplier", re.IGNORECASE)
_VENDOR_CODE = re.compile(
    r"(?:کد\s*وندور|vendor\s*code|کدوندور)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9_-]{2,15})",
    re.IGNORECASE,
)


def vendor_signals(message: str) -> dict[str, Any]:
    """Explicit vendor wording or a vendor code written in the message."""
    text = message or ""
    codes: list[str] = []
    for match in _VENDOR_CODE.finditer(text):
        code = match.group(1)
        if code not in codes:
            codes.append(code)
    return {"mentioned": bool(_VENDOR_WORD.search(text) or codes), "codes": codes}


def classification_gate(message: str, excerpts: str) -> str | None:
    """Skip the model only when neither the message nor Knowledge mentions a vendor."""
    if (excerpts or "").strip() or vendor_signals(message)["mentioned"]:
        return None
    return "No matching vendor knowledge"


def parse_classification(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    match = _JSON_OBJECT.search(text)
    if not match:
        raise ValueError("Classifier did not return JSON")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Classifier JSON must be an object")
    confidence = data.get("confidence") or 0
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    related = data.get("vendor_related")
    if isinstance(related, str):
        related = related.strip().lower() in {"1", "true", "yes"}
    return {
        "vendor_related": bool(related),
        "vendor_name": str(data.get("vendor_name") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
        "confidence": confidence,
    }


def knowledge_excerpts(message: str, *, limit: int = 4) -> tuple[str, list[str]]:
    """Retrieve vendor context from the Knowledge store. Empty when nothing matches."""
    signals = vendor_signals(message)
    questions = [f"vendor partner third-party integration {message[:400]}"]
    questions.extend(f"vendor code {code}" for code in signals["codes"])
    try:
        from slices.knowledge.rag.vector_store import get_knowledge_store

        store = get_knowledge_store()
    except Exception:
        return "", []
    parts: list[str] = []
    titles: list[str] = []
    seen: set[str] = set()
    for question in questions:
        try:
            hits = store.query(question=question, top_k=limit)
        except Exception:
            continue
        for hit in hits:
            content = str(hit.get("content") or "").strip()
            if not content or content[:180] in seen:
                continue
            seen.add(content[:180])
            title = str(hit.get("title") or hit.get("collection") or "knowledge")
            titles.append(title)
            parts.append(f"[{title}] {content[:500]}")
    return "\n".join(parts)[:2000], titles


def build_prompt(message: str, excerpts: str) -> str:
    signals = vendor_signals(message)
    codes = ", ".join(signals["codes"]) or "(none)"
    knowledge = excerpts.strip() or "(no matching knowledge page)"
    return (
        "You classify one chat message for a food-delivery engineering team.\n"
        "The message may be Persian or English.\n"
        "Mark vendor_related true when the message is about an external vendor, "
        "partner, PSP, supplier, or third-party integration.\n"
        "A vendor code in the message, or the words وندور / vendor / supplier, "
        "is enough even when Knowledge has no page for that vendor.\n"
        "Use Knowledge excerpts to fill vendor_name when they match. "
        "Otherwise put the vendor code from the message into vendor_name.\n"
        "Internal services alone, with no vendor wording and no vendor code, are not vendors.\n\n"
        f"Vendor codes found in the message: {codes}\n\n"
        f"Knowledge excerpts:\n{knowledge}\n\n"
        f"Message:\n{message[:4000]}\n\n"
        "Return only JSON with keys vendor_related (boolean), vendor_name (string), "
        "reason (short string), confidence (number from 0 to 1)."
    )


def _cursor_text(stdout: str) -> str:
    text = (stdout or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        for key in ("result", "text", "message", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return text


async def _classify_ollama(prompt: str, model: str) -> str:
    import httpx

    settings = get_settings()
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            url,
            json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        body = response.json()
    content = ((body.get("message") or {}).get("content")) or ""
    if not str(content).strip():
        raise ValueError("Ollama returned an empty classification")
    return str(content)


def _classify_cursor(prompt: str) -> str:
    from shared.cursor_cli.runner import CursorCliError, run_cursor_prompt

    try:
        result = run_cursor_prompt(
            prompt,
            output_format="text",
            mode="ask",
            timeout_seconds=90,
        )
    except CursorCliError as exc:
        raise RuntimeError(str(exc)) from exc
    if result.returncode != 0 and not (result.stdout or "").strip():
        detail = (result.stderr or "Cursor CLI failed").strip()
        raise RuntimeError(detail[:500])
    text = _cursor_text(result.stdout)
    if not text.strip():
        raise RuntimeError("Cursor CLI returned an empty classification")
    return text


def _cue_fallback(message: str, cfg_name: str, titles: list[str], detail: str) -> Classification | None:
    signals = vendor_signals(message)
    if not signals["codes"]:
        return None
    code = signals["codes"][0]
    return Classification(
        vendor_related=True,
        vendor_name=code,
        reason=f"Vendor code {code} is in the message. Model was not used: {detail}",
        confidence=0.7,
        classifier=cfg_name,
        knowledge_hits=titles,
        status="done",
    )


async def classify_message(message: str) -> Classification:
    """Classify using the message itself and Knowledge excerpts."""
    cfg = get_channel_alert_settings()
    excerpts, titles = knowledge_excerpts(message)
    skip = classification_gate(message, excerpts)
    if skip:
        return Classification(
            vendor_related=False,
            reason=skip,
            classifier=cfg.classifier,
            knowledge_hits=[],
            status="done",
        )
    prompt = build_prompt(message, excerpts)
    try:
        if cfg.classifier == "cursor_cli":
            raw = await asyncio.to_thread(_classify_cursor, prompt)
        else:
            raw = await _classify_ollama(prompt, cfg.ollama_model)
        parsed = parse_classification(raw)
    except Exception as exc:
        fallback = _cue_fallback(message, cfg.classifier, titles, str(exc))
        if fallback is not None:
            return fallback
        return Classification(
            vendor_related=False,
            reason=f"Classification failed: {exc}",
            classifier=cfg.classifier,
            knowledge_hits=titles,
            status="failed",
        )
    signals = vendor_signals(message)
    if signals["codes"] and not parsed["vendor_name"]:
        parsed["vendor_name"] = signals["codes"][0]
    if signals["codes"] and not parsed["vendor_related"]:
        parsed["vendor_related"] = True
        parsed["reason"] = parsed["reason"] or f"Vendor code {signals['codes'][0]} is in the message"
    if not parsed["vendor_related"]:
        parsed["vendor_name"] = ""
    return Classification(
        vendor_related=parsed["vendor_related"],
        vendor_name=parsed["vendor_name"],
        reason=parsed["reason"],
        confidence=parsed["confidence"],
        classifier=cfg.classifier,
        knowledge_hits=titles,
        status="done",
    )