"""The work-items API: create, list, update, reorder — owner-scoped.

Each work item hangs off a repository the caller owns. Dependencies must point
at items in the same repository (no dangling edges for blocker detection).
Design note: docs/architecture/PLANNING_SUITE.md.
"""

import uuid

from tests.conftest import auth_headers

REPO = "https://github.com/acme/demo"


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


async def _create_repo(client, headers) -> str:
    resp = await client.post("/v1/repositories", json={"url": REPO}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_item(client, headers, repo_id: str, **body) -> dict:
    body.setdefault("title", "Add password reset")
    resp = await client.post(f"/v1/repositories/{repo_id}/work-items", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_sets_planning_defaults(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)

    item = await _create_item(client, headers, repo_id, title="Add password reset")
    assert item["kind"] == "feature"
    assert item["status"] == "proposed"
    assert item["priority"] == "medium"
    assert item["estimate"] is None
    assert item["depends_on"] == []
    assert item["implemented_by_run_id"] is None


async def test_list_returns_items_in_board_order(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    await _create_item(client, headers, repo_id, title="First")
    await _create_item(client, headers, repo_id, title="Second")

    listed = (await client.get(f"/v1/repositories/{repo_id}/work-items", headers=headers)).json()
    assert [i["title"] for i in listed] == ["First", "Second"]


async def test_update_changes_only_the_sent_fields(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    item = await _create_item(client, headers, repo_id, title="Add password reset")

    resp = await client.patch(
        f"/v1/repositories/{repo_id}/work-items/{item['id']}",
        json={"status": "ready", "estimate": "small"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["status"] == "ready"
    assert updated["estimate"] == "small"
    assert updated["title"] == "Add password reset"  # untouched


async def test_dependency_must_be_in_the_same_repository(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    stranger = str(uuid.uuid4())

    resp = await client.post(
        f"/v1/repositories/{repo_id}/work-items",
        json={"title": "Wire the email", "depends_on": [stranger]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "dependency" in resp.json()["detail"].lower()


async def test_a_valid_dependency_is_accepted(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    base = await _create_item(client, headers, repo_id, title="Reset token model")

    dependent = await _create_item(
        client, headers, repo_id, title="Reset email", depends_on=[base["id"]]
    )
    assert dependent["depends_on"] == [base["id"]]


async def test_reorder_sets_board_positions(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    a = await _create_item(client, headers, repo_id, title="A")
    b = await _create_item(client, headers, repo_id, title="B")
    c = await _create_item(client, headers, repo_id, title="C")

    resp = await client.post(
        f"/v1/repositories/{repo_id}/work-items/reorder",
        json={"ordered_ids": [c["id"], a["id"], b["id"]]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert [i["title"] for i in resp.json()] == ["C", "A", "B"]

    listed = (await client.get(f"/v1/repositories/{repo_id}/work-items", headers=headers)).json()
    assert [i["title"] for i in listed] == ["C", "A", "B"]


async def test_work_items_are_owner_scoped(client):
    owner = _headers()
    intruder = _headers()
    repo_id = await _create_repo(client, owner)
    item = await _create_item(client, owner, repo_id, title="Secret plan")

    # the intruder cannot see, list against, or modify another owner's repo
    assert (
        await client.get(f"/v1/repositories/{repo_id}/work-items", headers=intruder)
    ).status_code == 404
    assert (
        await client.patch(
            f"/v1/repositories/{repo_id}/work-items/{item['id']}",
            json={"status": "done"},
            headers=intruder,
        )
    ).status_code == 404


async def test_create_rejects_a_blank_title(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    resp = await client.post(
        f"/v1/repositories/{repo_id}/work-items", json={"title": ""}, headers=headers
    )
    assert resp.status_code == 422


async def test_generate_roadmap_saves_work_items(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)

    resp = await client.post(
        f"/v1/repositories/{repo_id}/roadmap",
        json={"goal": "Add password reset by email"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert len(created) >= 1
    assert all(item["title"] for item in created)
    # a dependent item points at an earlier item's real id
    with_deps = [item for item in created if item["depends_on"]]
    ids = {item["id"] for item in created}
    assert all(dep in ids for item in with_deps for dep in item["depends_on"])

    # the roadmap is now the repository's backlog
    listed = (await client.get(f"/v1/repositories/{repo_id}/work-items", headers=headers)).json()
    assert [i["id"] for i in listed] == [i["id"] for i in created]


async def test_generate_roadmap_is_owner_scoped(client):
    owner = _headers()
    intruder = _headers()
    repo_id = await _create_repo(client, owner)
    resp = await client.post(
        f"/v1/repositories/{repo_id}/roadmap",
        json={"goal": "Add billing"},
        headers=intruder,
    )
    assert resp.status_code == 404


async def test_insights_flag_blockers_and_recommend_the_next_item(client):
    headers = _headers()
    repo_id = await _create_repo(client, headers)
    base = await _create_item(client, headers, repo_id, title="Reset token model", priority="low")
    dependent = await _create_item(
        client, headers, repo_id, title="Reset email", priority="critical", depends_on=[base["id"]]
    )

    insights = (
        await client.get(f"/v1/repositories/{repo_id}/work-items/insights", headers=headers)
    ).json()
    # the critical item waits on the unfinished base item, so the base is next
    assert [entry["title"] for entry in insights["blocked"]] == ["Reset email"]
    assert insights["blocked"][0]["waiting_on"] == [base["id"]]
    assert insights["recommended"]["id"] == base["id"]

    # finishing the dependency unblocks the critical item and changes the pick
    await client.patch(
        f"/v1/repositories/{repo_id}/work-items/{base['id']}",
        json={"status": "done"},
        headers=headers,
    )
    insights = (
        await client.get(f"/v1/repositories/{repo_id}/work-items/insights", headers=headers)
    ).json()
    assert insights["blocked"] == []
    assert insights["recommended"]["id"] == dependent["id"]


async def test_insights_are_owner_scoped(client):
    owner = _headers()
    intruder = _headers()
    repo_id = await _create_repo(client, owner)
    resp = await client.get(f"/v1/repositories/{repo_id}/work-items/insights", headers=intruder)
    assert resp.status_code == 404
