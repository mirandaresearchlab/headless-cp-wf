"""Tests that nextflow_schema.json agrees with the params block of nextflow.config.

nextflow.config holds the defaults that Nextflow uses. nextflow_schema.json describes the same
parameters for people: the documentation site makes the parameter reference from it. These tests
fail if somebody adds, removes or changes a parameter in one file but not in the other.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def config_params():
    """Read the parameter names and defaults from the params block of nextflow.config.

    Returns
    -------
    dict
        ``{name: default}``. The defaults are Python values: None, bool, int or str.
    """
    text = (ROOT / "nextflow.config").read_text(encoding="utf-8")
    block = re.search(r"(?ms)^params \{\n(.*?)^\}", text).group(1)
    params = {}

    # One parameter per line: "    name = value   // comment". The loop skips comment lines.
    for line in block.splitlines():
        match = re.match(r"\s+(\w+)\s*=\s*(.+?)\s*(//.*)?$", line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        if value == "null":
            params[name] = None
        elif value in ("true", "false"):
            params[name] = value == "true"
        elif re.fullmatch(r"-?\d+", value):
            params[name] = int(value)
        else:
            params[name] = value.strip("'\"")
    return params


def schema_params():
    """Read all parameters of nextflow_schema.json, from all its groups.

    Returns
    -------
    dict
        ``{name: property}``, where property is the JSON schema of the parameter.
    """
    schema = json.loads((ROOT / "nextflow_schema.json").read_text(encoding="utf-8"))
    params = {}
    for group in schema["$defs"].values():
        params.update(group["properties"])
    return params


def test_schema_and_config_have_the_same_parameters():
    """Check that each parameter of nextflow.config is in the schema, and the reverse."""
    assert sorted(schema_params()) == sorted(config_params())


def test_schema_defaults_agree_with_the_config():
    """Check that each schema default is the default in nextflow.config (no default = null)."""
    config = config_params()
    for name, prop in schema_params().items():
        assert prop.get("default") == config[name], name


def test_every_schema_group_is_used_and_every_parameter_is_described():
    """Check that allOf lists every group, and that each parameter has a type and a description."""
    schema = json.loads((ROOT / "nextflow_schema.json").read_text(encoding="utf-8"))
    used = {ref["$ref"].split("/")[-1] for ref in schema["allOf"]}
    assert used == set(schema["$defs"])
    for name, prop in schema_params().items():
        assert prop.get("type") and prop.get("description"), name


def test_params_files_use_only_known_parameters():
    """Check that each key of the params files in cp-configs/ is a parameter of the workflow.

    A misspelt key in a params file is ignored by Nextflow without a message.
    """
    yaml = pytest.importorskip("yaml")
    known = set(schema_params())
    for path in sorted((ROOT / "cp-configs").glob("*.yml")):
        keys = set(yaml.safe_load(path.read_text(encoding="utf-8")))
        assert keys <= known, (path.name, sorted(keys - known))


def test_berzelius_params_file_uses_the_pipelines_of_cp_configs():
    """Check that the Berzelius params file names both pipelines of cp-configs/, and that they exist."""
    yaml = pytest.importorskip("yaml")
    params = yaml.safe_load((ROOT / "cp-configs" / "berzelius_params.yml").read_text(encoding="utf-8"))
    for key in ("illum_pipeline", "pipeline"):
        name = Path(params[key]).name
        assert (ROOT / "cp-configs" / name).is_file(), name
