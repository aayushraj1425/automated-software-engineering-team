import base64
import re
import shutil
import subprocess

import pytest

from engine.deploy.frozen import freeze_checked_manifests, schema_reference_problems

CHECKED = """apiVersion: v1
kind: ConfigMap
metadata:
  name: checked-preview
data:
  message: 'Unicode works: 🧪; literal {{ lookup "v1" "Secret" "x" "y" }}'
"""


@pytest.mark.parametrize("key", ["$ref", "$dynamicRef", "$recursiveRef", "$id"])
def test_external_schema_references_are_blocked(key):
    assert schema_reference_problems({"properties": {"x": {key: "file:///etc/secrets"}}})
    assert not schema_reference_problems({"properties": {"x": {key: "#/definitions/local"}}})


def test_custom_meta_schema_is_blocked():
    assert schema_reference_problems({"$schema": "http://169.254.169.254/"})
    assert not schema_reference_problems({"$schema": "http://json-schema.org/draft-07/schema#"})


def test_frozen_chart_contains_only_trusted_literal_template(tmp_path):
    chart = freeze_checked_manifests(CHECKED, tmp_path / "frozen")
    template = (chart / "templates/resources.yaml").read_text(encoding="utf-8")
    match = re.fullmatch(r'\{\{ "([A-Za-z0-9+/=]+)" \| b64dec \}\}\n', template)
    assert match is not None
    assert base64.b64decode(match[1]).decode("utf-8") == CHECKED
    assert "lookup" not in template
    assert sorted(path.name for path in chart.iterdir()) == ["Chart.yaml", "templates"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="optional real Helm render")
def test_real_helm_emits_checked_literal_without_evaluating_it(tmp_path):
    chart = freeze_checked_manifests(CHECKED, tmp_path / "frozen")
    helm = shutil.which("helm")
    assert helm is not None
    result = subprocess.run(
        [helm, "template", "frozen-check", str(chart)],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert CHECKED.strip() in result.stdout
