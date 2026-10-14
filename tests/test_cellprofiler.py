"""Tests that run real CellProfiler in the pinned container.

These need Docker. Run them with `uv run pytest -m cellprofiler` (several minutes on
Apple Silicon, where the amd64 image runs under emulation).
"""

import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_workflow import nextflow_env

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "nextflow.config").read_text(encoding="utf-8")
IMAGE = re.search(r"container\s*=\s*'([^']+)'", CONFIG).group(1)

pytestmark = pytest.mark.cellprofiler

# Per-image object counts from the original prototype (commit b8b73b5), run with
# `-profile test,docker --save_masks false`. CellProfiler settings did not change since,
# so these must stay identical.
REFERENCE_COUNTS = {
    "plate1/site0_DNA.tif": 8,
    "plate1/site1_DNA.tif": 12,
    "plate1/site2_DNA.tif": 9,
    "plate2/site0_DNA.tif": 9,
    "plate2/site1_DNA.tif": 6,
    "plate2/site2_DNA.tif": 7,
}


@pytest.fixture(scope="module", autouse=True)
def require_docker():
    """Skip all tests of this file if Docker is missing, and pull the CellProfiler image if needed.

    pytest runs this fixture once, before the first test of the file (autouse).
    """
    if not shutil.which("docker"):
        pytest.skip("docker is not on PATH")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        pytest.skip("the Docker daemon is not running")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", IMAGE], check=True)


def in_container(workdir, command):
    """Run a bash command in the CellProfiler image.

    The repository (read-only) and the work folder are mounted at the same paths as on the host,
    and the command runs as the current user.

    Parameters
    ----------
    workdir : pathlib.Path
        The folder to mount and to start the command in.
    command : str
        The bash command.

    Returns
    -------
    subprocess.CompletedProcess
        The finished container, with its exit code and its output.
    """
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--entrypoint",
            "",
            "-u",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{ROOT}:{ROOT}:ro",
            "-v",
            f"{workdir}:{workdir}",
            "-w",
            str(workdir),
            IMAGE,
            "bash",
            "-c",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )


def patch(tmp_path, extra_module=None, chunked=True):
    """Optionally add a module to tests/test.cppipe, then run patch_cppipe.py on the pipeline.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the pipelines and the report.
    extra_module : str, optional
        The module to add and its settings, for example "Groups wants_groups=True".
        The default (None) adds no module.
    chunked : bool, optional
        If True (the default), give --chunked to patch_cppipe.py.

    Returns
    -------
    subprocess.CompletedProcess
        The finished container. It also has the attribute ``report``: the patch report as a
        dict ({} if no report was written).
    """
    source = ROOT / "tests" / "test.cppipe"
    steps = []
    if extra_module:
        source = tmp_path / "input.cppipe"
        steps.append(
            f"python3 {ROOT}/tests/cp_make_pipeline.py {ROOT}/tests/test.cppipe {source} {extra_module}"
        )
    steps.append(
        f"python3 {ROOT}/bin/patch_cppipe.py --input {source} --output patched.cppipe "
        f"--report report.json{' --chunked' if chunked else ''}"
    )
    result = in_container(tmp_path, " && ".join(steps))
    report_path = tmp_path / "report.json"
    result.report = json.loads(report_path.read_text()) if report_path.exists() else {}
    return result


def test_patch_adds_masks_and_removes_batch_module(tmp_path):
    """Check that the test pipeline gets mask writers for Nuclei and Cells and loses CreateBatchFiles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result = patch(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.report["objects"] == ["Nuclei", "Cells"]
    assert [mask["object"] for mask in result.report["masks_managed"]] == ["Nuclei", "Cells"]
    assert result.report["removed_modules"] == ["CreateBatchFiles"]
    assert result.report["chunk_unsafe_modules"] == []
    assert "CreateBatchFiles" not in (tmp_path / "patched.cppipe").read_text()


@pytest.mark.parametrize(
    "module",
    [
        "CorrectIlluminationCalculate each_or_all=All:\\ Across\\ cycles",
        "LoadData",
        "Groups wants_groups=True",
        "TrackObjects",
    ],
)
def test_chunking_a_pipeline_that_needs_all_image_sets_fails(tmp_path, module):
    """Check that each module that needs all image sets stops a chunked run.

    The error message must name the module.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    module : str
        The module to add and its settings (one value per test run, from parametrize).
    """
    result = patch(tmp_path, module)
    assert result.returncode == 1
    assert "must process all image sets in one CellProfiler run" in result.stderr
    assert module.split()[0] in result.stderr


def test_same_pipeline_without_chunking_is_allowed(tmp_path):
    """Check that the same pipeline runs without chunking, and that the report still lists the module.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result = patch(tmp_path, "CorrectIlluminationCalculate each_or_all=All:\\ Across\\ cycles", chunked=False)
    assert result.returncode == 0, result.stderr
    assert "CorrectIlluminationCalculate" in result.report["chunk_unsafe_modules"][0]


def test_per_image_illumination_correction_can_be_chunked(tmp_path):
    """Check that illumination correction per image ('Each') allows chunks.

    This mode does not combine image sets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result = patch(tmp_path, "CorrectIlluminationCalculate each_or_all=Each")
    assert result.returncode == 0, result.stderr
    assert result.report["chunk_unsafe_modules"] == []


def read_csv(path):
    """Read a CSV file into a list of dicts.

    Parameters
    ----------
    path : pathlib.Path
        The CSV file.

    Returns
    -------
    list of dict
        One dict per row, with the column names as keys.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_test_profile_end_to_end_matches_reference(tmp_path):
    """Run the test profile with real CellProfiler and compare the results with the reference.

    Each image must have its reference nuclei count, and each image set must have both masks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result = subprocess.run(
        [
            "nextflow",
            "-log",
            str(tmp_path / "nextflow.log"),
            "run",
            str(ROOT),
            "-profile",
            "test,docker",
            "-work-dir",
            str(tmp_path / "work"),
            "--outdir",
            str(tmp_path / "results"),
        ],
        cwd=tmp_path,
        env=nextflow_env(),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    features = tmp_path / "results" / "features"
    images = read_csv(features / "MyExpt_Image.csv")
    manifest = read_csv(features / "mask_manifest.csv")
    nuclei = read_csv(features / "MyExpt_Nuclei.csv")

    # Every image set appears once, with the reference object count.
    path_of = {row["CPNF_GlobalImageNumber"]: row["InputPath_DNA"] for row in manifest}
    counts = {path_of[row["CPNF_GlobalImageNumber"]]: float(row["Count_Nuclei"]) for row in images}
    assert counts == REFERENCE_COUNTS

    # Object rows agree with the per-image counts, and every image set has both masks on disk.
    assert len(nuclei) == sum(REFERENCE_COUNTS.values())
    assert sorted(row["MaskObject"] for row in manifest) == ["Cells"] * 6 + ["Nuclei"] * 6
    for row in manifest:
        assert (tmp_path / "results" / row["MaskPath"]).is_file()
        assert "/work/" not in ",".join(row.values()), "manifest must not contain task work paths"
