"""Row-level security: Postgres refuses another user's rows, no WHERE needed.

conftest applies the policies right after creating the schema, so the entire
suite already runs under FORCE ROW LEVEL SECURITY; these tests attack the
seam directly — raw SQL through pinned sessions, the exact shape a buggy
route (a forgotten WHERE clause) would take. Design note:
docs/architecture/ROW_LEVEL_SECURITY.md.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from engine.db.models import (
    AgentRun,
    Conversation,
    IntegrationConnection,
    ProviderKey,
    Repository,
)
from engine.db.rls import USER_OWNED_TABLES
from engine.db.session import session_scope


@pytest.fixture(autouse=True)
async def _require_non_superuser(prepared_db):
    """Superusers bypass RLS entirely — the policies exist but protect
    nothing. Fresh compose volumes create asep as NOSUPERUSER
    (infra/docker/postgres-init); older checkouts must rebuild theirs once:
    backup create → docker compose down -v → up → backup restore."""
    async with session_scope() as session:
        superuser = (
            await session.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar()
    if superuser:
        pytest.fail(
            "the test role is a superuser, which bypasses row-level security —"
            " rebuild the dev Postgres volume (see CLAUDE.md Gotchas)"
        )


async def _seed_two_owners(prefix: str) -> tuple[str, str]:
    """Two users, one repository each, written through the trusted context."""
    alice, bob = f"{prefix}_alice_{uuid.uuid4().hex[:6]}", f"{prefix}_bob_{uuid.uuid4().hex[:6]}"
    async with session_scope() as session:
        session.add(Repository(owner_id=alice, url=f"https://github.com/{alice}/repo"))
        session.add(Repository(owner_id=bob, url=f"https://github.com/{bob}/repo"))
        await session.commit()
    return alice, bob


async def test_pinned_session_reads_only_its_own_rows(prepared_db):
    alice, bob = await _seed_two_owners("read")

    async with session_scope(user_id=alice) as session:
        owners = (await session.execute(select(Repository.owner_id))).scalars().all()

    assert alice in owners
    assert bob not in owners  # no WHERE clause anywhere — Postgres filtered


async def test_pinned_session_updates_zero_foreign_rows(prepared_db):
    """Even aiming at the row by primary key, the write lands on nothing."""
    alice, bob = await _seed_two_owners("write")

    async with session_scope() as session:
        bob_repo_id = (
            await session.execute(select(Repository.id).where(Repository.owner_id == bob))
        ).scalar_one()

    async with session_scope(user_id=alice) as session:
        result = await session.execute(
            text("UPDATE repositories SET status = 'tampered' WHERE id = :id"),
            {"id": bob_repo_id},
        )
        await session.commit()
    assert getattr(result, "rowcount", None) == 0

    async with session_scope() as session:
        status = (
            await session.execute(select(Repository.status).where(Repository.id == bob_repo_id))
        ).scalar_one()
    assert status == "connected"  # untouched


async def test_pinned_session_cannot_insert_rows_for_someone_else(prepared_db):
    alice, bob = f"ins_alice_{uuid.uuid4().hex[:6]}", f"ins_bob_{uuid.uuid4().hex[:6]}"

    async with session_scope(user_id=alice) as session:
        session.add(Repository(owner_id=bob, url="https://github.com/planted/repo"))
        with pytest.raises(ProgrammingError, match="row-level security policy"):
            await session.commit()


async def test_session_scope_asserts_the_explicit_service_context(prepared_db):
    """The runner, webhooks, and workers go through session_scope(), which
    sets app.service='1' — the *explicit* internal context that sees
    everything. (Unset context is no longer trusted — see the deny test.)"""
    alice, bob = await _seed_two_owners("svc")

    async with session_scope() as session:
        owners = (await session.execute(select(Repository.owner_id))).scalars().all()
    assert alice in owners and bob in owners


async def test_a_session_with_no_context_is_denied_everything(prepared_db):
    """Deny by default: a raw session outside the engine's helpers — the
    shape of a forgotten pin — reads zero rows, updates zero rows even by
    primary key, and cannot insert."""
    from sqlalchemy.exc import ProgrammingError as _ProgrammingError

    from engine.db.session import get_sessionmaker

    alice, bob = await _seed_two_owners("deny")
    async with session_scope() as session:
        target_id = (
            await session.execute(select(Repository.id).where(Repository.owner_id == alice))
        ).scalar_one()

    async with get_sessionmaker()() as bare:  # no pin, no service flag
        owners = (await bare.execute(select(Repository.owner_id))).scalars().all()
        assert owners == []

        result = await bare.execute(
            text("UPDATE repositories SET status = 'tampered' WHERE id = :id"),
            {"id": target_id},
        )
        await bare.commit()
        assert getattr(result, "rowcount", None) == 0

    async with get_sessionmaker()() as bare:
        bare.add(Repository(owner_id=bob, url="https://github.com/deny/insert"))
        with pytest.raises(_ProgrammingError, match="row-level security policy"):
            await bare.commit()


async def test_pin_survives_a_mid_request_commit(prepared_db):
    """set_config is transaction-local; the after_begin hook must re-apply it
    on the *next* transaction, or everything after a commit leaks."""
    alice, bob = await _seed_two_owners("commit")

    async with session_scope(user_id=alice) as session:
        session.add(Repository(owner_id=alice, url=f"https://github.com/{alice}/second"))
        await session.commit()  # ends the pinned transaction

        owners = (await session.execute(select(Repository.owner_id))).scalars().all()

    assert owners.count(alice) == 2
    assert bob not in owners


def _rows_for(user_id: str) -> tuple[Repository, list]:
    """One row in every policy-carrying table, owned by ``user_id``. The
    repository comes separately: AgentRun carries its FK without a mapped
    relationship, so the flush order must be made explicit."""
    repository = Repository(
        id=uuid.uuid4(), owner_id=user_id, url=f"https://github.com/{user_id}/repo"
    )
    return repository, [
        Conversation(user_id=user_id),
        AgentRun(user_id=user_id, repository_id=repository.id, request="prove RLS"),
        ProviderKey(user_id=user_id, provider="anthropic", encrypted_key="x", last4="1234"),
        IntegrationConnection(user_id=user_id, encrypted_config="x"),
    ]


async def test_every_protected_table_filters_by_owner(prepared_db):
    """One sweep across all five policy-carrying tables (the very list the
    policies are generated from): a stranger's rows are invisible to a pinned
    session's bare SELECT."""
    me, stranger = f"all_me_{uuid.uuid4().hex[:6]}", f"all_other_{uuid.uuid4().hex[:6]}"

    async with session_scope() as session:  # trusted context seeds both users
        for user_id in (me, stranger):
            repository, dependents = _rows_for(user_id)
            session.add(repository)
            await session.flush()
            session.add_all(dependents)
        await session.commit()

    async with session_scope(user_id=me) as session:
        for table, column in USER_OWNED_TABLES.items():
            owners = (
                (await session.execute(text(f"SELECT {column} FROM {table}")))  # noqa: S608
                .scalars()
                .all()
            )
            assert me in owners, table
            assert stranger not in owners, table
