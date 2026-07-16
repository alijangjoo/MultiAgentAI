#!/usr/bin/env python
"""CLI helper to verify Jira and GitLab connectivity before running agents."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shared.integrations.health import IntegrationHealthService  # noqa: E402


async def main() -> int:
    service = IntegrationHealthService()
    result = await service.check_all()

    print("=== Integration Health Check ===\n")
    print("Jira:")
    print(json.dumps(result["jira"], indent=2, default=str))
    print("\nGitLab:")
    print(json.dumps(result["gitlab"], indent=2, default=str))

    if result["all_ok"]:
        print("\nAll integrations OK.")
        return 0

    print("\nOne or more integrations failed. Check .env credentials and network access.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
