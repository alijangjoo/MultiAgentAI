"""Basic tests for branch naming and domain models."""

import pytest

from shared.models.domain import SubTask
from shared.utils.branch_naming import build_feature_branch_name, slugify


def test_slugify():
    assert slugify("Create API for Contract") == "create-api-for-contract"


def test_build_feature_branch_name():
    branch = build_feature_branch_name(
        task_key="VEN-100",
        task_summary="Create API for contract management",
        short_description="create-api-for-contract",
    )
    assert branch == "Feature/ven-100-create-api-for-contract"


def test_subtask_max_hours():
    subtask = SubTask(title="Test", description="Desc", estimated_hours=8)
    assert subtask.estimated_hours == 8

    with pytest.raises(Exception):
        SubTask(title="Test", description="Desc", estimated_hours=10)
