import re
import unicodedata


def slugify(text: str, max_length: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_length].rstrip("-")


def build_feature_branch_name(task_key: str, task_summary: str, short_description: str) -> str:
    """
    Format: feature/[task-key]-[short-description]
    Example: feature/ven-100-create-api-for-contract
    """
    key_part = task_key.lower()
    desc_part = slugify(short_description or task_summary)
    return f"feature/{key_part}-{desc_part}"
