"""Health score for Vendor rules 4 and 5, plus WIP age."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from slices.jira_reporter.calendar import business_days_inclusive, is_workday, parse_jira_datetime

MEMBERS = (
    {"id": "omid", "name": "AlaBeigi, Omid", "family": "alabeigi"},
    {"id": "kambiz", "name": "Babaei, Kambiz", "family": "babaei"},
    {"id": "ali", "name": "Jangjoo, Ali", "family": "jangjoo"},
)

WIP_LIMIT = 1
STALE_AFTER = 2
REVIEW_QUEUE_AFTER = 1


def stage_of(status: str | None) -> str:
    compact = (status or "").lower().replace(" ", "").replace("_", "").replace("-", "")
    if "codereview" in compact or compact == "review":
        return "code_review"
    if "progress" in compact or compact == "doing":
        return "in_progress"
    if compact in {"done", "closed", "resolved"}:
        return "done"
    if compact in {"todo", "todo", "open"} or "todo" in compact:
        return "todo"
    return "other"


def match_member(assignee: str | None) -> tuple[dict[str, str] | None, str | None]:
    if not assignee or not str(assignee).strip():
        return None, "Unassigned"
    folded = str(assignee).casefold().replace(",", " ")
    hits = [member for member in MEMBERS if member["family"] in folded]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, f"Ambiguous name: {assignee}"
    return None, f"Outside the team: {assignee}"


def _events(issue: dict[str, Any]) -> list[dict[str, Any]]:
    events = issue.get("changelog") or []
    return events if isinstance(events, list) else []


def _last_entry(issue: dict[str, Any], stage: str) -> datetime | None:
    found: datetime | None = None
    for event in _events(issue):
        if stage_of(str(event.get("to") or "")) != stage:
            continue
        parsed = parse_jira_datetime(str(event.get("at") or ""))
        if parsed is not None and (found is None or parsed > found):
            found = parsed
    return found


def _saw_stage(issue: dict[str, Any], stage: str) -> bool:
    if stage_of(issue.get("status")) == stage:
        return True
    return any(stage_of(str(event.get("to") or "")) == stage for event in _events(issue))


def _active_exception(exceptions: list[dict[str, Any]], person_id: str, today: date) -> dict[str, Any] | None:
    chosen: dict[str, Any] | None = None
    for item in exceptions:
        if str(item.get("person_id") or "") != person_id:
            continue
        try:
            until = date.fromisoformat(str(item.get("until") or ""))
        except ValueError:
            continue
        if until < today:
            continue
        chosen = item
    return chosen


def _extra_wip(keys: list[str], exception: dict[str, Any] | None) -> int:
    normalized = [str(key).upper() for key in keys]
    if len(normalized) <= WIP_LIMIT:
        return 0
    if not exception:
        return len(normalized) - WIP_LIMIT
    allowed = {str(key).upper() for key in (exception.get("keys") or [])}
    if allowed and set(normalized) <= allowed:
        return 0
    uncovered = [key for key in normalized if key not in allowed]
    return max(0, len(uncovered) - WIP_LIMIT) if allowed else len(normalized) - WIP_LIMIT


def _wip_points(extra: int) -> int:
    if extra <= 0:
        return 0
    points = 12 + max(0, extra - 1) * 8
    return min(32, points)


def build_report(
    snapshot: dict[str, Any],
    exceptions: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or datetime.now().astimezone().date()
    exceptions = exceptions or []
    sprints = list(snapshot.get("sprints") or [])
    assumed = _assumed_sprint(sprints)
    issues = list(snapshot.get("issues") or [])
    if assumed is not None:
        sprint_id = assumed.get("id")
        scoped = [issue for issue in issues if sprint_id is None or issue.get("sprint_id") in {None, sprint_id}]
    else:
        scoped = issues

    footnotes: list[str] = []
    if len(sprints) > 1 and assumed is not None:
        footnotes.append(f"Several sprints are open. Health uses \"{assumed.get('name')}\".")
    if snapshot.get("truncated"):
        footnotes.append("Issue list stopped at 200 and may be incomplete.")

    people = {
        member["id"]: {
            "id": member["id"],
            "name": member["name"],
            "wip": [],
            "zero_wip": False,
        }
        for member in MEMBERS
    }
    stale: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    counts = {"todo": 0, "in_progress": 0, "code_review": 0, "done": 0, "other": 0}
    by_type: dict[str, dict[str, int]] = {}
    uncertain_age = 0
    added_after_start = 0
    sprint_start = parse_jira_datetime(str((assumed or {}).get("start") or ""))
    sprint_end = parse_jira_datetime(str((assumed or {}).get("end") or ""))

    for issue in scoped:
        status_stage = stage_of(issue.get("status"))
        counts[status_stage] = counts.get(status_stage, 0) + 1
        issue_type = str(issue.get("issue_type") or "Unknown")
        bucket = by_type.setdefault(issue_type, {"todo": 0, "in_progress": 0, "code_review": 0, "done": 0, "other": 0})
        bucket[status_stage] = bucket.get(status_stage, 0) + 1
        created = parse_jira_datetime(str(issue.get("created") or ""))
        if sprint_start and created and created.date() > sprint_start.date():
            added_after_start += 1

        member, note = match_member(issue.get("assignee"))
        if note and note not in footnotes and note != "Unassigned":
            footnotes.append(note)
        if member is None:
            continue
        card = _issue_card(issue, member["name"], today)
        if status_stage == "in_progress":
            people[member["id"]]["wip"].append(card)
            if card["age_days"] is None:
                uncertain_age += 1
            elif card["age_days"] > STALE_AFTER and card["age_certain"]:
                stale.append(card)
        elif status_stage == "code_review" and card["age_days"] is not None and card["age_days"] > REVIEW_QUEUE_AFTER:
            review_queue.append(card)
        elif status_stage == "done" and _events(issue) and not _saw_stage(issue, "code_review"):
            skips.append({
                "key": issue.get("key"),
                "summary": issue.get("summary") or "",
                "assignee": member["name"],
                "detail": "Moved to Done without Code Review",
            })

    if uncertain_age:
        footnotes.append("Some WIP items have no In Progress changelog, so age is not certain.")

    penalties: list[dict[str, Any]] = []
    hard = 0
    stale_points = 0
    review_points = 0
    cards = []
    for member in MEMBERS:
        row = people[member["id"]]
        keys = [item["key"] for item in row["wip"]]
        exception = _active_exception(exceptions, member["id"], today)
        extra = _extra_wip(keys, exception)
        if extra:
            points = _wip_points(extra)
            hard += 1
            penalties.append({
                "code": "extra_wip",
                "points": points,
                "hard": True,
                "person": member["name"],
                "detail": f"{len(keys)} WIP items without a recorded exception",
            })
        elif is_workday(today) and not keys:
            penalties.append({
                "code": "zero_wip",
                "points": 4,
                "hard": False,
                "person": member["name"],
                "detail": "No WIP today",
            })
        cards.append({
            "id": member["id"],
            "name": member["name"],
            "wip_count": len(keys),
            "wip": row["wip"],
            "exception": exception,
            "next_step": _next_step(row["wip"], extra),
        })

    for item in stale:
        if stale_points >= 30:
            break
        take = min(10, 30 - stale_points)
        stale_points += take
        hard += 1
        penalties.append({
            "code": "stale_wip",
            "points": take,
            "hard": True,
            "person": item["assignee"],
            "detail": f"{item['key']} has been In Progress for more than {STALE_AFTER} workdays",
        })
    for item in skips:
        hard += 1
        penalties.append({
            "code": "skipped_review",
            "points": 15,
            "hard": True,
            "person": item["assignee"],
            "detail": f"{item['key']} never passed Code Review",
        })
    for item in review_queue:
        if review_points >= 18:
            break
        take = min(6, 18 - review_points)
        review_points += take
        penalties.append({
            "code": "review_queue",
            "points": take,
            "hard": False,
            "person": item["assignee"],
            "detail": f"{item['key']} has stayed in Code Review for more than one workday",
        })

    score = max(0, 100 - sum(item["points"] for item in penalties))
    soft_watch = any(item["code"] == "zero_wip" for item in penalties)
    if hard >= 2:
        verdict = "Unhealthy"
    elif hard == 1 or soft_watch or score < 85:
        verdict = "Watch"
    else:
        verdict = "Healthy"
    reasons = [item["detail"] for item in penalties if item["hard"]] or [
        item["detail"] for item in penalties
    ]
    if not reasons:
        reasons = ["WIP and the Code Review flow look healthy for all three people"]

    total = sum(counts.values()) or 1
    done_ratio = round(100 * counts["done"] / total, 1)
    time_ratio = _time_ratio(sprint_start, sprint_end, today)
    oldest = max(scoped_wip(cards), key=lambda item: item["age_days"] or 0, default=None)
    recent_done = _recent_done(scoped, today)
    forecast = _forecast(counts, recent_done, sprint_end, today)

    return {
        "board_name": snapshot.get("board_name") or "Ven Board",
        "today": today.isoformat(),
        "workday": is_workday(today),
        "verdict": verdict,
        "score": score,
        "hard_violations": hard,
        "reasons": reasons[:6],
        "penalties": penalties,
        "sprint": {
            "assumed": assumed,
            "open": [{"id": item.get("id"), "name": item.get("name")} for item in sprints],
            "counts": counts,
            "by_type": by_type,
            "done_percent": done_ratio,
            "elapsed_percent": time_ratio,
            "added_after_start": added_after_start,
            "oldest_wip": oldest,
            "forecast": forecast,
        },
        "people": cards,
        "stale": sorted(stale, key=lambda item: item["age_days"] or 0, reverse=True),
        "skips": skips,
        "review_queue": review_queue,
        "questions": _questions(cards, skips, stale),
        "footnotes": footnotes,
        "rules": ["4", "5"],
    }


def scoped_wip(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        rows.extend(card["wip"])
    return rows


def _assumed_sprint(sprints: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sprints:
        return None
    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("start") or "")
    return sorted(sprints, key=sort_key)[-1]


def _issue_card(issue: dict[str, Any], assignee: str, today: date) -> dict[str, Any]:
    status_stage = stage_of(issue.get("status"))
    entered = _last_entry(issue, status_stage if status_stage in {"in_progress", "code_review"} else "in_progress")
    certain = entered is not None
    age = business_days_inclusive(entered.date(), today) if entered else None
    updated = parse_jira_datetime(str(issue.get("updated") or ""))
    return {
        "key": issue.get("key"),
        "summary": issue.get("summary") or "",
        "status": issue.get("status") or "",
        "issue_type": issue.get("issue_type") or "",
        "assignee": assignee,
        "age_days": age,
        "age_certain": certain,
        "updated": updated.date().isoformat() if updated else None,
    }


def _next_step(wip: list[dict[str, Any]], extra: int) -> str:
    if extra:
        keys = ", ".join(str(item["key"]) for item in wip[:3])
        return f"Move one item to Code Review, or record an exception for {keys}"
    if not wip:
        return "Move one Task or Sub-task to In Progress"
    oldest = max(wip, key=lambda item: item["age_days"] or 0)
    if (oldest.get("age_days") or 0) > STALE_AFTER:
        return f"Finish {oldest['key']} or move it to Code Review"
    return f"Keep {wip[0]['key']} moving to Code Review"


def _time_ratio(start: datetime | None, end: datetime | None, today: date) -> float | None:
    if start is None or end is None:
        return None
    total = business_days_inclusive(start.date(), end.date())
    if total <= 0:
        return None
    elapsed = business_days_inclusive(start.date(), min(today, end.date()))
    return round(100 * elapsed / total, 1)


def _recent_done(issues: list[dict[str, Any]], today: date) -> int:
    window_start = today - timedelta(days=14)
    count = 0
    for issue in issues:
        for event in _events(issue):
            if stage_of(str(event.get("to") or "")) != "done":
                continue
            parsed = parse_jira_datetime(str(event.get("at") or ""))
            if parsed is None:
                continue
            if business_days_inclusive(parsed.date(), today) <= 3 and parsed.date() >= window_start:
                count += 1
                break
    return count


def _forecast(counts: dict[str, int], recent_done: int, end: datetime | None, today: date) -> dict[str, Any]:
    remaining = counts["todo"] + counts["in_progress"] + counts["code_review"] + counts["other"]
    left = 0
    if end is not None and end.date() >= today:
        left = business_days_inclusive(today, end.date())
    weak = recent_done == 0
    unfinished = remaining
    if not weak and left:
        pace = recent_done / 3
        unfinished = max(0, round(remaining - pace * left))
    return {
        "recent_done": recent_done,
        "workdays_left": left,
        "still_open_forecast": unfinished,
        "weak": weak,
    }


def _questions(cards: list[dict[str, Any]], skips: list[dict[str, Any]], stale: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for card in cards:
        if card["wip_count"] > WIP_LIMIT and not card.get("exception"):
            keys = " and ".join(str(item["key"]) for item in card["wip"][:2])
            questions.append(
                f"Will {keys} reach Code Review today, or is the extra WIP for {card['name']} agreed until a date?"
            )
    for item in skips[:2]:
        questions.append(f"Why was {item['key']} closed without Code Review?")
    for item in stale[:2]:
        if len(questions) >= 3:
            break
        questions.append(f"{item['key']} has been In Progress for {item['age_days']} workdays.")
    return questions[:3]