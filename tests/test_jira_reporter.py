"""Navid health rules: one WIP and the path through Code Review."""

from datetime import date, timedelta

from slices.jira_reporter.calendar import business_days_inclusive
from slices.jira_reporter.rules import build_report, match_member


def _wednesday() -> date:
    day = date(2026, 11, 1)
    while day.weekday() != 2:
        day += timedelta(days=1)
    return day


def _issue(key, assignee, status, changelog, issue_type="Task", sprint_id=1):
    return {
        "key": key,
        "summary": key,
        "status": status,
        "issue_type": issue_type,
        "assignee": assignee,
        "created": "2026-11-01T09:00:00.000+0330",
        "updated": "2026-11-04T09:00:00.000+0330",
        "changelog": changelog,
        "sprint_id": sprint_id,
    }


def _snapshot(issues):
    return {
        "board_name": "Ven Board",
        "sprints": [{"id": 1, "name": "Sprint 23", "start": "2026-11-01T00:00:00.000+0330", "end": "2026-11-20T00:00:00.000+0330"}],
        "issues": issues,
    }


def test_workweek_age_matches_the_vendor_calendar():
    wednesday = _wednesday()
    saturday = wednesday + timedelta(days=3)
    sunday = saturday + timedelta(days=1)
    assert saturday.weekday() == 5
    assert business_days_inclusive(wednesday, saturday) == 2
    assert business_days_inclusive(wednesday, sunday) == 3


def test_display_name_order_still_matches_the_family_name():
    member, note = match_member("Omid AlaBeigi")
    assert note is None
    assert member["id"] == "omid"
    other, outside = match_member("Someone Else")
    assert other is None
    assert outside.startswith("Outside the team")


def test_two_wip_is_watch_and_three_day_age_is_stale():
    wednesday = _wednesday()
    sunday = wednesday + timedelta(days=4)
    report = build_report(
        _snapshot([
            _issue("VEN-101", "AlaBeigi, Omid", "In Progress", [
                {"at": f"{wednesday.isoformat()}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-118", "AlaBeigi, Omid", "In Progress", [
                {"at": f"{sunday.isoformat()}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-110", "Babaei, Kambiz", "In Progress", [
                {"at": f"{sunday.isoformat()}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-104", "Jangjoo, Ali", "Code Review", [
                {"at": f"{sunday.isoformat()}T09:00:00.000+0330", "from": "In Progress", "to": "Code Review"},
            ]),
        ]),
        today=sunday,
    )
    assert report["verdict"] == "Unhealthy"
    assert report["hard_violations"] == 2
    assert any(item["key"] == "VEN-101" for item in report["stale"])
    assert report["people"][0]["wip_count"] == 2


def test_done_without_code_review_is_a_hard_skip():
    today = _wednesday()
    report = build_report(
        _snapshot([
            _issue("VEN-099", "Jangjoo, Ali", "Done", [
                {"at": f"{today.isoformat()}T09:00:00.000+0330", "from": "In Progress", "to": "Done"},
            ]),
            _issue("VEN-100", "Babaei, Kambiz", "In Progress", [
                {"at": f"{today.isoformat()}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-101", "AlaBeigi, Omid", "In Progress", [
                {"at": f"{today.isoformat()}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
        ]),
        today=today,
    )
    assert report["skips"][0]["key"] == "VEN-099"
    assert report["hard_violations"] >= 1


def test_registered_keys_waive_the_second_wip():
    today = _wednesday() + timedelta(days=7)
    while not today.weekday() in {5, 6, 0, 1, 2}:
        today += timedelta(days=1)
    entered = today.isoformat()
    report = build_report(
        _snapshot([
            _issue("VEN-201", "AlaBeigi, Omid", "In Progress", [
                {"at": f"{entered}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-202", "AlaBeigi, Omid", "In Progress", [
                {"at": f"{entered}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-203", "Babaei, Kambiz", "In Progress", [
                {"at": f"{entered}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
            _issue("VEN-204", "Jangjoo, Ali", "In Progress", [
                {"at": f"{entered}T09:00:00.000+0330", "from": "To Do", "to": "In Progress"},
            ]),
        ]),
        exceptions=[{
            "person_id": "omid",
            "until": (today + timedelta(days=2)).isoformat(),
            "keys": ["VEN-201", "VEN-202"],
            "reason": "هماهنگ شد",
        }],
        today=today,
    )
    assert report["verdict"] == "Healthy"
    assert report["hard_violations"] == 0