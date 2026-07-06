# Demo Item Service

A deliberately small service used as the target repository for ASEP agent
runs — evaluation and demos happen against a copy of this folder, never
against a real project.

- `app/main.py` — FastAPI app: health check and an items API
- `app/config.py` — service settings
- `web/` — a static page that lists the items
- `tests/test_app.py` — the service's own tests

Run it locally:

```sh
pip install -r requirements.txt
uvicorn app.main:app --reload
```
