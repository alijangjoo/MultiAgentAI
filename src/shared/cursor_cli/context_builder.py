from core.config import get_settings
from shared.cursor_cli.models import ReviewContext
from shared.models.domain import MergeRequestInfo
from slices.knowledge.review_docs import get_review_docs_service
from slices.knowledge.review_package import ReviewKnowledgePackage


def build_review_context(
    *,
    mr: MergeRequestInfo,
    task_key: str,
    development_summary: str,
    code_context: str,
    mr_changes: list[dict] | None,
    knowledge_package: ReviewKnowledgePackage | None = None,
    language: str = "en",
    include_specs: bool | None = None,
) -> ReviewContext:
    """Map MR + knowledge package fields into the Cursor CLI review context schema."""
    settings = get_settings()
    send_specs = (
        settings.cursor_review_include_specs
        if include_specs is None
        else include_specs
    )

    docs = get_review_docs_service()
    git_diff = docs.format_mr_diff(mr_changes)
    if not mr_changes and code_context and code_context.strip():
        git_diff = f"{git_diff}\n\n## Extra code context\n{code_context[:4000]}"

    specs_parts: list[str] = []
    review_rules: str | None = None
    extra_context: dict[str, str] = {}

    if knowledge_package:
        # TODO: re-enable task PRD / Code Specs / Architecture Specs when context size is tuned.
        if send_specs:
            if knowledge_package.prd.strip():
                specs_parts.append(f"## Task PRD\n{knowledge_package.prd.strip()}")
            if knowledge_package.code_specs.strip():
                specs_parts.append(f"## Code Specs\n{knowledge_package.code_specs.strip()}")
            if knowledge_package.architecture_specs.strip():
                specs_parts.append(
                    f"## Architecture Specs\n{knowledge_package.architecture_specs.strip()}"
                )
        review_rules = knowledge_package.review_rules.strip() or None

        if send_specs:
            if knowledge_package.adrs.strip():
                extra_context["adrs"] = knowledge_package.adrs.strip()
            if knowledge_package.ubiquitous_language.strip():
                extra_context["ubiquitous_language"] = knowledge_package.ubiquitous_language.strip()
            if knowledge_package.source_context.strip():
                extra_context["source_context"] = knowledge_package.source_context.strip()
        if knowledge_package.tech_stack.strip():
            extra_context["tech_stack"] = knowledge_package.tech_stack.strip()
    elif send_specs and development_summary.strip():
        specs_parts.append(development_summary.strip())

    if task_key:
        extra_context["jira_ticket"] = task_key
    if mr.source_branch:
        extra_context["source_branch"] = mr.source_branch
    if mr.target_branch:
        extra_context["target_branch"] = mr.target_branch

    return ReviewContext(
        title=mr.title,
        description=development_summary.strip() or None,
        git_diff=git_diff,
        specs="\n\n".join(specs_parts).strip() or None,
        review_rules=review_rules,
        extra_context=extra_context or None,
        language=language,
    )
