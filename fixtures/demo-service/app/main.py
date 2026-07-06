from fastapi import FastAPI, HTTPException

from app.config import settings

app = FastAPI(title="Demo Item Service")

ITEMS = ["alpha", "beta", "gamma"]


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/items")
def list_items():
    return {"items": ITEMS}


@app.get("/items/{item_id}")
def get_item(item_id: int):
    if item_id < 0 or item_id > len(ITEMS):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item": ITEMS[item_id]}
