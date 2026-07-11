"""The durable work_items backlog model: defaults, dependencies, run linkage.

Exercises the WorkItem ORM model against a real database: a freshly created
item gets sensible defaults, its depends_on list round-trips through JSONB, and
deleting the run that implemented it nulls the link (SET NULL) rather than
cascading the item away — a planned item outlives the run that built it. Design
note: docs/architecture/PLANNING_SUITE.md.
"""

import uuid

from sqlalchemy import select

from engine.db.enums import Priority, WorkItemKind, WorkItemStatus
from engine.db.models import AgentRun, Repository, WorkItem
from engine.db.session import session_scope


async def _make_repo() -> uuid.UUID:
    async with session_scope() as session:
        repo = Repository(owner_id="user_test", url="https://github.com/acme/demo")
        session.add(repo)
        await session.flush()
        repo_id = repo.id
        await session.commit()
        return repo_id


async def test_new_work_item_has_planning_defaults(prepared_db):
    repo_id = await _make_repo()
    async with session_scope() as session:
        item = WorkItem(repository_id=repo_id, title="Add password reset")
        session.add(item)
        await session.flush()
        item_id = item.id
        await session.commit()

    async with session_scope() as session:
        item = await session.get(WorkItem, item_id)
        assert item is not None
        assert item.kind == WorkItemKind.FEATURE
        assert item.status == WorkItemStatus.PROPOSED
        assert item.priority == Priority.MEDIUM
        assert item.estimate is None  # not sized until the agent estimates it
        assert item.depends_on == []
        assert item.position == 0


async def test_depends_on_round_trips_through_jsonb(prepared_db):
    repo_id = await _make_repo()
    dependency_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    async with session_scope() as session:
        item = WorkItem(
            repository_id=repo_id,
            title="Wire the reset email",
            depends_on=dependency_ids,
            estimate="small",
            priority=Priority.HIGH,
        )
        session.add(item)
        await session.flush()
        item_id = item.id
        await session.commit()

    async with session_scope() as session:
        item = await session.get(WorkItem, item_id)
        assert item is not None
        assert item.depends_on == dependency_ids
        assert item.estimate == "small"
        assert item.priority == Priority.HIGH


async def test_deleting_the_implementing_run_nulls_the_link(prepared_db):
    """A planned item outlives the run that built it: SET NULL, not cascade."""
    repo_id = await _make_repo()
    run_id = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            AgentRun(id=run_id, user_id="user_test", repository_id=repo_id, request="build it")
        )
        item = WorkItem(
            repository_id=repo_id,
            title="Ship password reset",
            status=WorkItemStatus.DONE,
            implemented_by_run_id=run_id,
        )
        session.add(item)
        await session.flush()
        item_id = item.id
        await session.commit()

    async with session_scope() as session:
        run = await session.get(AgentRun, run_id)
        assert run is not None
        await session.delete(run)
        await session.commit()

    async with session_scope() as session:
        item = await session.get(WorkItem, item_id)
        assert item is not None  # the work item survives
        assert item.implemented_by_run_id is None  # only the link is cleared

    async with session_scope() as session:
        # sanity: the item is still findable by repository
        rows = (
            (await session.execute(select(WorkItem).where(WorkItem.repository_id == repo_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
