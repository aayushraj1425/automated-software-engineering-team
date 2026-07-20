"""Organization-aware sharing: the active organization opens shared rows.

Two layers under test, both stating the same rule (owner OR active org):
the RLS policies attacked with raw SQL through pinned sessions, and the API
routes through real requests carrying the ``org`` claim.
Design note: docs/architecture/ORGANIZATION_SHARING.md.
"""

import uuid

import pytest
from sqlalchemy import select, text

from engine.db.models import AgentRun, Conversation, Repository
from engine.db.session import session_scope
from tests.conftest import auth_headers


def _ids(prefix: str) -> tuple[str, str, str]:
    """Two users and the organization they share, unique per test."""
    tag = uuid.uuid4().hex[:6]
    return f"{prefix}_alice_{tag}", f"{prefix}_bob_{tag}", f"{prefix}_org_{tag}"


async def _seed_shared_repository(owner: str, org: str) -> uuid.UUID:
    """A repository the owner connected while the organization was active."""
    repo = Repository(
        id=uuid.uuid4(), owner_id=owner, org_id=org, url=f"https://github.com/{owner}/shared"
    )
    async with session_scope() as session:
        session.add(repo)
        await session.commit()
    return repo.id


# ── The RLS seam: raw SQL, no WHERE clause, Postgres decides ─────────────────


async def test_org_member_sees_the_shared_repository(prepared_db):
    alice, bob, org = _ids("see")
    await _seed_shared_repository(alice, org)

    async with session_scope(user_id=bob, org_id=org) as session:
        owners = (await session.execute(select(Repository.owner_id))).scalars().all()
    assert alice in owners  # Bob never owned it — the org clause let him in


async def test_without_the_org_active_the_row_stays_hidden(prepared_db):
    alice, bob, org = _ids("hide")
    await _seed_shared_repository(alice, org)

    async with session_scope(user_id=bob) as session:  # personal context
        owners = (await session.execute(select(Repository.owner_id))).scalars().all()
    assert alice not in owners

    async with session_scope(user_id=bob, org_id=f"other_{org}") as session:
        owners = (await session.execute(select(Repository.owner_id))).scalars().all()
    assert alice not in owners


async def test_org_member_can_update_the_shared_row(prepared_db):
    """Members are equal collaborators — writes pass USING and WITH CHECK."""
    alice, bob, org = _ids("upd")
    repo_id = await _seed_shared_repository(alice, org)

    async with session_scope(user_id=bob, org_id=org) as session:
        result = await session.execute(
            text("UPDATE repositories SET status = 'indexing' WHERE id = :id"), {"id": repo_id}
        )
        await session.commit()
    assert getattr(result, "rowcount", None) == 1


async def test_agent_runs_share_the_same_way(prepared_db):
    alice, bob, org = _ids("run")
    repo_id = await _seed_shared_repository(alice, org)
    async with session_scope() as session:
        session.add(
            AgentRun(user_id=alice, org_id=org, repository_id=repo_id, request="shared work")
        )
        await session.commit()

    async with session_scope(user_id=bob, org_id=org) as session:
        run_owners = (await session.execute(select(AgentRun.user_id))).scalars().all()
    assert alice in run_owners

    async with session_scope(user_id=bob) as session:
        run_owners = (await session.execute(select(AgentRun.user_id))).scalars().all()
    assert alice not in run_owners


async def test_conversations_stay_personal_even_with_a_matching_org(prepared_db):
    """Conversations carry org_id but grant nothing on it — a chat with the
    assistant is a private notebook (the design note's table)."""
    alice, bob, org = _ids("conv")
    async with session_scope() as session:
        session.add(Conversation(user_id=alice, org_id=org, title="alice's private chat"))
        await session.commit()

    async with session_scope(user_id=bob, org_id=org) as session:
        owners = (await session.execute(select(Conversation.user_id))).scalars().all()
    assert alice not in owners


async def test_pinned_insert_into_the_active_org_is_allowed(prepared_db):
    """WITH CHECK: creating a resource under the active organization works
    from a pinned session (the exact shape connect_repository takes)."""
    alice, _, org = _ids("ins")
    async with session_scope(user_id=alice, org_id=org) as session:
        session.add(Repository(owner_id=alice, org_id=org, url=f"https://github.com/{alice}/new"))
        await session.commit()  # would raise on a policy violation


# ── The API seam: real requests carrying the org claim ──────────────────────


@pytest.mark.usefixtures("prepared_db")
async def test_api_lists_the_org_mates_repository(client):
    alice, bob, org = _ids("api")
    repo_id = await _seed_shared_repository(alice, org)

    with_org = await client.get("/v1/repositories", headers=auth_headers(bob, org_id=org))
    assert with_org.status_code == 200
    assert str(repo_id) in [r["id"] for r in with_org.json()]

    without_org = await client.get("/v1/repositories", headers=auth_headers(bob))
    assert str(repo_id) not in [r["id"] for r in without_org.json()]


@pytest.mark.usefixtures("prepared_db")
async def test_destroying_a_shared_repository_takes_an_admin(client):
    """Members create and work; destroying a teammate's shared thing takes
    an admin — the org_role claim gates it (ORGANIZATION_ROLES.md)."""
    alice, bob, org = _ids("role")
    repo_id = await _seed_shared_repository(alice, org)

    # A plain member cannot disconnect a teammate's shared repository…
    member = await client.delete(
        f"/v1/repositories/{repo_id}", headers=auth_headers(bob, org_id=org, org_role="member")
    )
    assert member.status_code == 403
    assert "admin" in member.json()["detail"]

    # …an admin can — and the connector always could (their own repository).
    admin = await client.delete(
        f"/v1/repositories/{repo_id}", headers=auth_headers(bob, org_id=org, org_role="admin")
    )
    assert admin.status_code == 204

    own_id = await _seed_shared_repository(alice, org)
    owner = await client.delete(
        f"/v1/repositories/{own_id}", headers=auth_headers(alice, org_id=org, org_role="member")
    )
    assert owner.status_code == 204


@pytest.mark.usefixtures("prepared_db")
async def test_removing_the_team_key_takes_its_contributor_or_an_admin(client):
    alice, bob, org = _ids("keyrole")
    await client.put(
        "/v1/provider-keys/anthropic",
        json={"key": "sk-ant-team-key-1234", "share_with_organization": True},
        headers=auth_headers(alice, org_id=org),
    )

    member = await client.delete(
        "/v1/provider-keys/anthropic?shared=true",
        headers=auth_headers(bob, org_id=org, org_role="member"),
    )
    assert member.status_code == 403

    contributor = await client.delete(
        "/v1/provider-keys/anthropic?shared=true",
        headers=auth_headers(alice, org_id=org, org_role="member"),
    )
    assert contributor.status_code == 204


@pytest.mark.usefixtures("prepared_db")
async def test_api_point_lookup_follows_the_same_rule(client):
    alice, bob, org = _ids("apiget")
    repo_id = await _seed_shared_repository(alice, org)

    shared = await client.get(
        f"/v1/repositories/{repo_id}/graph", headers=auth_headers(bob, org_id=org)
    )
    assert shared.status_code == 200

    hidden = await client.get(f"/v1/repositories/{repo_id}/graph", headers=auth_headers(bob))
    assert hidden.status_code == 404
