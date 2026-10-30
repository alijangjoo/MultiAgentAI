from shared.cursor_cli.models import ReviewContext

_REVIEW_INSTRUCTIONS = """You are a senior code reviewer.

Review the change using ONLY the context embedded below.
Do NOT run shell commands (including git).
Do NOT modify files.
Do NOT ask clarifying questions — produce the review now.
Do NOT mention Ask mode, Agent mode, or readiness to review — analyze the git diff below immediately.

Focus on:
- Correctness and edge cases
- Spec / requirements compliance
- Security and data-handling risks
- Maintainability and clear defects
- Concrete, actionable findings (file/hunk when possible)
"""

_JSON_OUTPUT_CONTRACT = """
Return one JSON object with keys: approved (bool), summary (string),
findings (array of strings), suggestions (array of strings).

Each findings/suggestions item MUST be a single string in this exact shape:
  "[ERROR] path/File.cs:LINE - RR-012: description"
  "[WARNING] path/File.cs:LINE - RR-014: description"
  "[SUGGESTION] path/File.cs:LINE - concrete fix"

Example:
{
  "approved": false,
  "summary": "Review of the diff reveals multiple violations: ...",
  "findings": [
    "[ERROR] src/AppCore/.../ScheduledOrderCommandHandler.cs:1 - RR-013: Every *CommandHandler must have a matching *CommandValidator.",
    "[ERROR] src/AppCore/.../ScheduledOrderCommandHandler.cs:1 - RR-012: namespace declaration must be the first code construct (before using directives)."
  ],
  "suggestions": [
    "[SUGGESTION] src/AppCore/.../ScheduledOrderCommandHandler.cs:1 - Move namespace declaration before using directives using file-scoped namespace."
  ]
}

Use LINE=1 when the issue starts at file top. Set approved=false when any [ERROR] / merge-blocking rule fails.
Return ONLY the JSON object — no markdown fences or extra commentary.
"""

_TEXT_OUTPUT_CONTRACT = """
Structure the response as:
1. Summary (2-4 sentences)
2. Findings (severity: blocker / major / minor / nit) — empty list if none
3. Spec gaps (if specs were provided)
4. Verdict: APPROVE | REQUEST_CHANGES | COMMENT
"""

_SKILL_REVIEW_INSTRUCTIONS = """You are Sentinel, a senior .NET code reviewer.

Apply the **sentinel-review** skill rules from `.cursor/skills/sentinel-review/SKILL.md`
AND the **Active Review Rules** section below (both are mandatory).

Review ONLY the git diff embedded below. Do NOT browse, open, or search other files in the workspace.
Do NOT run shell commands (including git). Do NOT modify files.
Do NOT ask clarifying questions — produce the review immediately from the diff alone.

The diff uses `### path/to/File.cs` section headers followed by unified diff hunks.
Lines starting with `+` are added/changed code — evaluate every such line against all rules.
"""

_SKILL_REVIEW_CHECKLIST = """
Mandatory checklist before you respond (do not skip):
1. RR-012: In each new/changed `.cs` file, `namespace` must be the first code construct (before any `using`). File-scoped namespaces are preferred.
2. RR-013: Each new `*CommandHandler.cs` must have a matching `*CommandValidator.cs` in the same MR.
3. RR-014: `.cs` files must not end with a trailing blank line after the closing `}`.
Report every violation as a finding string. Set approved=false when any [ERROR] / merge-blocking rule fails.
"""


def build_skill_review_prompt(context: ReviewContext, *, output_format: str = "json") -> str:
    """Skill-based review prompt; JSON preferred, text format used as CLI retry fallback."""
    fmt = (output_format or "json").strip().lower()
    contract = _JSON_OUTPUT_CONTRACT if fmt == "json" else _TEXT_OUTPUT_CONTRACT
    parts: list[str] = [_SKILL_REVIEW_INSTRUCTIONS.strip(), "", contract.strip(), ""]

    parts.append(f"Respond in language: {context.language}")
    parts.append("")

    parts.append("## Git diff (review this)\n```diff\n" + context.git_diff.rstrip() + "\n```\n")

    if context.title:
        parts.append(f"## Change title\n{context.title.strip()}\n")
    if context.description:
        parts.append(f"## Change description\n{context.description.strip()}\n")

    if context.specs:
        parts.append(f"## Specs\n{context.specs.strip()}\n")

    if context.review_rules:
        parts.append(f"## Active Review Rules (mandatory)\n{context.review_rules.strip()}\n")

    if context.extra_context:
        for key, value in context.extra_context.items():
            label = str(key).replace("_", " ").strip().title() or "Extra"
            text = value if isinstance(value, str) else repr(value)
            parts.append(f"## {label}\n{str(text).strip()}\n")

    parts.append(_SKILL_REVIEW_CHECKLIST.strip())
    parts.append("")
    parts.append("Apply the sentinel-review skill rules and produce the review now.")
    return "\n".join(parts)


def build_review_prompt(context: ReviewContext, *, output_format: str = "json") -> str:
    if context.use_review_skill:
        return build_skill_review_prompt(context, output_format=output_format)

    fmt = (output_format or "json").strip().lower()
    parts: list[str] = [_REVIEW_INSTRUCTIONS.strip(), ""]

    if fmt == "json":
        parts.append(_JSON_OUTPUT_CONTRACT.strip())
    else:
        parts.append(_TEXT_OUTPUT_CONTRACT.strip())
    parts.append("")

    parts.append(f"Respond in language: {context.language}")
    parts.append("")

    parts.append("## Git diff (review this)\n```diff\n" + context.git_diff.rstrip() + "\n```\n")

    if context.title:
        parts.append(f"## Change title\n{context.title.strip()}\n")
    if context.description:
        parts.append(f"## Change description\n{context.description.strip()}\n")

    if context.specs:
        parts.append(f"## Specs\n{context.specs.strip()}\n")

    if context.review_rules:
        parts.append(f"## Review rules\n{context.review_rules.strip()}\n")

    if context.extra_context:
        for key, value in context.extra_context.items():
            label = str(key).replace("_", " ").strip().title() or "Extra"
            text = value if isinstance(value, str) else repr(value)
            parts.append(f"## {label}\n{str(text).strip()}\n")

    parts.append("Produce the review now.")
    return "\n".join(parts)
