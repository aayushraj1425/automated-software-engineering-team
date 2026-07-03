"""Export the engine's OpenAPI spec to stdout (no server needed).

Used by packages/shared to generate the TypeScript client types:
    uv run python -m engine.openapi_export > openapi.json
"""

import json
import sys

from engine.main import app


def main() -> None:
    json.dump(app.openapi(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
