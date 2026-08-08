async def test_healthz_is_public(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_reports_ready_when_database_reachable(client):
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "database": "ok"}


async def test_readyz_reports_503_when_database_unreachable(client, monkeypatch):
    # A readiness probe's whole job is to fail when the dependency is down, so
    # traffic is held back. Point the check at an engine whose connection raises.
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("database is down")

    monkeypatch.setattr("engine.api.health.get_engine", lambda: _BrokenEngine())

    resp = await client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable", "database": "unreachable"}
