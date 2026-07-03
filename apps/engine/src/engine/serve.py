"""Dev-server entrypoint that owns the event loop.

psycopg async cannot run on Windows' default ProactorEventLoop, and uvicorn's
CLI creates the loop itself — so we set the selector policy and run the server
inside our own loop. Reload in dev comes from wrapping this in `watchfiles`
(see package.json), which restarts the whole process.
"""

import asyncio
import sys

import uvicorn


async def _serve() -> None:
    config = uvicorn.Config("engine.main:app", host="127.0.0.1", port=8000, log_level="info")
    await uvicorn.Server(config).serve()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
