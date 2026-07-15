"""Every API route refuses unauthenticated callers — enforced by a sweep.

Auth is a per-route dependency (`Depends(require_service_auth)`), so a new
route that forgets it would ship an open endpoint without any single review
catching it. This sweep walks the real route table and calls every one
without credentials: anything answering 2xx is a hole. Finding from the
security-boundary audit (docs/security/SECURITY_AUDIT.md).
"""

from fastapi.routing import APIRoute

from engine.main import app

# The only deliberately token-free routes. /healthz is the probe endpoint;
# the GitHub webhook authenticates by HMAC signature instead (and fails
# closed without one, so an unauthenticated call is still refused).
PUBLIC_PATHS = {"/healthz"}
SIGNATURE_AUTHENTICATED_PATHS = {"/v1/webhooks/github"}


def _walk(routes) -> list[APIRoute]:
    """Flatten the route table (FastAPI nests included routers)."""
    found = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):  # fastapi._IncludedRouter
            found.extend(_walk(route.original_router.routes))
        elif hasattr(route, "routes"):
            found.extend(_walk(route.routes))
    return found


def _api_routes() -> list[tuple[str, str]]:
    """(method, concrete path) for every route, path params filled in."""
    calls = []
    for route in _walk(app.routes):
        path = route.path
        for name in route.param_convertors:
            # Any well-formed value works: auth must reject before lookup.
            value = "00000000-0000-0000-0000-000000000000"
            path = path.replace("{" + name + "}", value)
        calls.extend((method, path) for method in route.methods or () if method != "HEAD")
    return calls


async def test_every_route_refuses_unauthenticated_callers(client):
    routes = _api_routes()
    assert len(routes) > 20  # the sweep really saw the app, not a stub

    holes = []
    for method, path in routes:
        if path in PUBLIC_PATHS:
            continue
        # Signature-authenticated routes also land here: with no secret
        # configured the HMAC check fails closed, which is still a 401.
        response = await client.request(method, path)
        if response.status_code != 401:
            holes.append(f"{method} {path} -> {response.status_code}")

    assert not holes, "routes reachable without a service token:\n" + "\n".join(holes)


async def test_healthz_is_the_only_public_route(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
