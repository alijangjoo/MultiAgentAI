"""Build QA Agent prompts from branch context."""

from shared.qa.models import QaContext

_QA_INSTRUCTIONS = """You are a senior QA engineer following a QA Maturity Framework.

Analyze the feature branch diff against Acceptance Criteria and Feature Brief.
Generate test assets and assess release readiness.

Do NOT run shell commands. Do NOT modify files.
Do NOT ask clarifying questions — produce the QA analysis now from the embedded context.
"""

_JSON_OUTPUT_CONTRACT = """
Return ONE JSON object with these keys:
- ready (bool): true if AC coverage is sufficient for QA sign-off
- verdict (string): PASS | PASS_WITH_GAPS | FAIL | NEEDS_INPUT
- summary (string): 2-5 sentence QA summary in the requested language
- test_cases (array): each item has id, title, preconditions, steps (array of strings),
  expected_result, priority (critical|high|medium|low), type (functional|regression|edge_case|integration),
  linked_ac (AC id or null)
- use_cases (array): each item has id, actor, goal, main_flow (array), alternate_flows (array)
- critical_flows (array of strings): impacted critical flows and regression risk
- ac_coverage (array): each item has criterion_id, criterion, status (covered|partial|missing|untestable), evidence
- gaps (array of strings): missing tests, untested paths, spec/code mismatches
- automation_suggestions (array of strings): pytest/jest/cypress candidates for release pipeline
- missing_inputs (array of strings): empty only if inputs were sufficient; otherwise list what the user must fill

If Acceptance Criteria or Feature Brief are placeholders/TBD/empty sections, set verdict=NEEDS_INPUT
and list required fields in missing_inputs. Still generate best-effort test cases from the diff.

Return ONLY the JSON object — no markdown fences or extra commentary.
"""


def build_qa_prompt(context: QaContext) -> str:
    parts: list[str] = [
        _QA_INSTRUCTIONS.strip(),
        "",
        _JSON_OUTPUT_CONTRACT.strip(),
        "",
        f"Respond in language: {context.language}",
        "",
    ]

    if context.task_key:
        parts.extend([f"## Jira / Task Key\n{context.task_key}", ""])
    if context.title:
        parts.extend([f"## Title\n{context.title}", ""])

    parts.extend([
        f"## Branch\nSource: `{context.branch_name}` → Target: `{context.target_branch}`",
        "",
    ])

    if context.feature_brief and context.feature_brief.strip():
        parts.extend([f"## Feature Brief / PRD\n{context.feature_brief.strip()}", ""])
    else:
        parts.append("## Feature Brief / PRD\n(not provided — infer from diff only)\n")

    if context.acceptance_criteria and context.acceptance_criteria.strip():
        parts.extend([f"## Acceptance Criteria\n{context.acceptance_criteria.strip()}", ""])
    else:
        parts.append("## Acceptance Criteria\n(not provided — infer from diff only)\n")

    if context.extra_context:
        for key, value in context.extra_context.items():
            if value and value.strip():
                parts.extend([f"## {key.replace('_', ' ').title()}\n{value.strip()}", ""])

    parts.extend([
        "## Code Changes (git diff)",
        context.git_diff.strip() or "(empty diff)",
    ])

    return "\n".join(parts)
