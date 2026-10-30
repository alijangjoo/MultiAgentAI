"""Parse QA Agent JSON responses."""

from __future__ import annotations

import json
import re
from typing import Any

from shared.qa.models import AcCoverageItem, QaResult, TestCaseItem, UseCaseItem


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _parse_test_cases(items: Any) -> list[TestCaseItem]:
    if not isinstance(items, list):
        return []
    result: list[TestCaseItem] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, str):
            result.append(TestCaseItem(id=f"TC-{idx}", title=item))
            continue
        if not isinstance(item, dict):
            continue
        steps = item.get("steps")
        result.append(
            TestCaseItem(
                id=str(item.get("id") or f"TC-{idx}"),
                title=str(item.get("title") or item.get("name") or f"Test case {idx}"),
                preconditions=str(item.get("preconditions") or ""),
                steps=_as_str_list(steps),
                expected_result=str(item.get("expected_result") or item.get("expected") or ""),
                priority=str(item.get("priority") or "medium"),
                type=str(item.get("type") or "functional"),
                linked_ac=item.get("linked_ac"),
            )
        )
    return result


def _parse_use_cases(items: Any) -> list[UseCaseItem]:
    if not isinstance(items, list):
        return []
    result: list[UseCaseItem] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, str):
            result.append(UseCaseItem(id=f"UC-{idx}", actor="User", goal=item))
            continue
        if not isinstance(item, dict):
            continue
        result.append(
            UseCaseItem(
                id=str(item.get("id") or f"UC-{idx}"),
                actor=str(item.get("actor") or "User"),
                goal=str(item.get("goal") or item.get("title") or ""),
                main_flow=_as_str_list(item.get("main_flow")),
                alternate_flows=_as_str_list(item.get("alternate_flows")),
            )
        )
    return result


def _parse_ac_coverage(items: Any) -> list[AcCoverageItem]:
    if not isinstance(items, list):
        return []
    result: list[AcCoverageItem] = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, str):
            result.append(AcCoverageItem(criterion_id=f"AC-{idx}", criterion=item, status="unknown"))
            continue
        if not isinstance(item, dict):
            continue
        result.append(
            AcCoverageItem(
                criterion_id=str(item.get("criterion_id") or item.get("id") or f"AC-{idx}"),
                criterion=str(item.get("criterion") or item.get("text") or ""),
                status=str(item.get("status") or "unknown"),
                evidence=str(item.get("evidence") or ""),
            )
        )
    return result


def parse_qa_response(content: str) -> QaResult:
    text = (content or "").strip()
    data: dict[str, Any] = {}
    if text:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                pass

    if not data:
        return QaResult(
            ready=False,
            verdict="FAIL",
            summary=text[:2000] if text else "Empty QA response",
            gaps=["Could not parse structured QA JSON from agent output"],
        )

    ready = data.get("ready")
    if ready is None:
        verdict = str(data.get("verdict") or "PENDING").upper()
        ready = verdict == "PASS"

    return QaResult(
        ready=bool(ready),
        verdict=str(data.get("verdict") or "PENDING").upper(),
        summary=str(data.get("summary") or "").strip(),
        test_cases=_parse_test_cases(data.get("test_cases")),
        use_cases=_parse_use_cases(data.get("use_cases")),
        critical_flows=_as_str_list(data.get("critical_flows")),
        ac_coverage=_parse_ac_coverage(data.get("ac_coverage")),
        gaps=_as_str_list(data.get("gaps")),
        automation_suggestions=_as_str_list(data.get("automation_suggestions")),
        missing_inputs=_as_str_list(data.get("missing_inputs")),
    )
