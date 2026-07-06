from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_items():
    response = client.get("/items")
    assert response.status_code == 200
    assert response.json()["items"] == ["alpha", "beta", "gamma"]


def test_get_first_item():
    response = client.get("/items/0")
    assert response.status_code == 200
    assert response.json()["item"] == "alpha"


def test_unknown_item_is_404():
    response = client.get("/items/99")
    assert response.status_code == 404
