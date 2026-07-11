"""The Scrum Master: validate a roadmap, then persist it with resolved deps.

Validation is a pure function; persistence writes to the durable backlog and
turns position-based dependencies ("item 2 needs item 1") into real work-item
ids. Offline (LLM_FAKE=1, set in conftest) generate_roadmap returns a fixed
roadmap so the path runs without a model. Design note:
docs/architecture/PLANNING_SUITE.md.
"""

import uuid

import pytest

from engine.agents.scrum_master import (
    RoadmapError,
    generate_roadmap,
    persist_roadmap,
    validate_roadmap,
)
from engine.db.models import Repository
from engine.db.session import session_scope


def test_validate_rejects_an_empty_roadmap():
    with pytest.raises(RoadmapError):
        validate_roadmap({"items": []})


def test_validate_rejects_a_forward_dependency():
    # item 1 cannot depend on item 2 (a later item) — the graph must be acyclic.
    roadmap = {
        "items": [
            {"title": "First", "depends_on": [2]},
            {"title": "Second", "depends_on": []},
        ]
    }
    with pytest.raises(RoadmapError):
        validate_roadmap(roadmap)


def test_validate_coerces_stray_enum_labels():
    roadmap = {
        "items": [
            {"title": "Do it", "kind": "epic", "priority": "urgent", "estimate": "xl"},
        ]
    }
    clean = validate_roadmap(roadmap)["items"][0]
    assert clean["kind"] == "feature"  # unknown kind → default
    assert clean["priority"] == "medium"  # unknown priority → default
    assert clean["estimate"] is None  # unknown estimate → cleared


async def test_generate_offline_returns_a_valid_roadmap():
    roadmap = await generate_roadmap("Add password reset")
    assert 1 <= len(roadmap["items"]) <= 20
    assert all(item["title"] for item in roadmap["items"])


async def test_persist_resolves_dependencies_to_ids(prepared_db):
    async with session_scope() as session:
        repo = Repository(owner_id="user_test", url="https://github.com/acme/demo")
        session.add(repo)
        await session.flush()
        repo_id = repo.id
        await session.commit()

    roadmap = validate_roadmap(
        {
            "items": [
                {"title": "Foundations", "milestone": "Foundations", "depends_on": []},
                {"title": "Core", "milestone": "Core flow", "depends_on": [1]},
                {"title": "Polish", "milestone": "Core flow", "depends_on": [2]},
            ]
        }
    )
    async with session_scope() as session:
        created = await persist_roadmap(session, repo_id, roadmap)

    assert [item.title for item in created] == ["Foundations", "Core", "Polish"]
    assert [item.position for item in created] == [0, 1, 2]
    # "Core" depends on "Foundations" by id; "Polish" on "Core".
    assert created[0].depends_on == []
    assert created[1].depends_on == [str(created[0].id)]
    assert created[2].depends_on == [str(created[1].id)]
    # every stored dependency id is a real, parseable work-item id
    for dep in created[2].depends_on:
        uuid.UUID(dep)
