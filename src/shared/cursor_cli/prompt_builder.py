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
Each findings/suggestions item MUST be a single string like "[ERROR] path/File.cs:12 - message", not an object.
Use LINE=0 when unknown. Set approved=false when the active Review Rules make any finding merge-blocking.
Return ONLY the JSON object — no markdown fences or extra commentary.
"""

_TEXT_OUTPUT_CONTRACT = """
Structure the response as:
1. Summary (2-4 sentences)
2. Findings (severity: blocker / major / minor / nit) — empty list if none
3. Spec gaps (if specs were provided)
4. Verdict: APPROVE | REQUEST_CHANGES | COMMENT
"""


def build_review_prompt(context: ReviewContext, *, output_format: str = "json") -> str:
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
