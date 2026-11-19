"""Create a trusted Helm chart that emits an already-checked manifest verbatim.

The source repository's templates are rendered without cluster credentials.
Installation must never evaluate those templates with privileged credentials.
This chart contains only one trusted b64dec expression and no repository code.
"""

import base64
from pathlib import Path
from typing import Any


def schema_reference_problems(document: Any) -> list[str]:
    """Schema validation during credential-free rendering must not fetch URLs."""
    allowed_meta = {
        "http://json-schema.org/draft-04/schema#",
        "https://json-schema.org/draft-04/schema#",
        "http://json-schema.org/draft-06/schema#",
        "https://json-schema.org/draft-06/schema#",
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema#",
    }
    stack = [document]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if (
                    key in ("$ref", "$dynamicRef", "$recursiveRef", "$id", "id")
                    and isinstance(value, str)
                    and not value.startswith("#")
                ):
                    return ["values.schema.json: external schema references are forbidden"]
                if key == "$schema" and (not isinstance(value, str) or value not in allowed_meta):
                    return ["values.schema.json: unsupported external meta-schema"]
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return []


def freeze_checked_manifests(rendered: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    templates = destination / "templates"
    templates.mkdir()
    (destination / "Chart.yaml").write_text(
        "apiVersion: v2\nname: asep-validated-preview\nversion: 0.1.0\ntype: application\n",
        encoding="utf-8",
    )
    # Encoding also prevents literal {{...}} inside a checked ConfigMap from
    # becoming a template expression on the installation render.
    payload = base64.b64encode(rendered.encode("utf-8")).decode("ascii")
    (templates / "resources.yaml").write_text(
        '{{ "' + payload + '" | b64dec }}\n', encoding="utf-8"
    )
    return destination
