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


# Per-object features of the same run (tests/reference/README.md tells how they were made).
REFERENCE = ROOT / "tests" / "reference"

# Relative tolerance for feature values. On 2026-10-15 the official image (Python 3.8, NumPy 1.24.4) and the
# conda build without a container (Python 3.9, NumPy 1.26.4) differed by at most 8e-6, in a Zernike feature.
# 1e-4 allows such rounding, but finds a changed segmentation or measurement. abs=1e-9 is for values near 0.
FEATURE_RTOL = 1e-4

# Columns that the comparison skips. Location_MaxIntensity_* is the position of the brightest pixel. If two
# pixels have the same maximum, CellProfiler builds can report either one: nucleus 7 of plate1/site2 has two
# pixels with the value 3238, and the reference has (97, 66) where a CI run had (99, 59). The maximum value
# itself (Intensity_MaxIntensity_*) is compared.
UNSTABLE_COLUMNS = ("Location_MaxIntensity_",)


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

    The function mounts the repository (read-only) and the work folder at the same paths as on the host.
    The command runs as the current user.

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


def patch(tmp_path, extra_module=None, chunked=True, source=None, options=""):
    """Optionally add a module to a test pipeline, then run patch_cppipe.py on the pipeline.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the pipelines and the report.
    extra_module : str, optional
        The module to add and its settings, for example "Groups wants_groups=True".
        The default (None) adds no module.
    chunked : bool, optional
        If True (the default), give --chunked to patch_cppipe.py.
    source : pathlib.Path, optional
        The pipeline to start from. The default is tests/test.cppipe.
    options : str, optional
        More options for patch_cppipe.py, for example "--illum".

    Returns
    -------
    subprocess.CompletedProcess
        The finished container. It also has the attribute ``report``: the patch report as a
        dict ({} if patch_cppipe.py wrote no report).
    """
    source = source or ROOT / "tests" / "test.cppipe"
    steps = []
    if extra_module:
        steps.append(
            f"python3 {ROOT}/tests/cp_make_pipeline.py {source} {tmp_path / 'input.cppipe'} {extra_module}"
        )
        source = tmp_path / "input.cppipe"
    steps.append(
        f"python3 {ROOT}/bin/patch_cppipe.py --input {source} --output patched.cppipe "
        f"--report report.json{' --chunked' if chunked else ''} {options}"
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


def assert_features_match_reference(features):
    """Compare the Nuclei and Cells tables of a run with the reference tables, value by value.

    The reference tables (made before plates) number the image sets in CPNF_GlobalImageNumber. The merge now
    writes that number into ImageNumber itself: the order of the image sets (plate1, then plate2) is the same.

    Parameters
    ----------
    features : pathlib.Path
        The cellprofiler_tables/ folder of the run.
    """
    for table in ("Nuclei", "Cells"):
        expected = read_csv(REFERENCE / f"MyExpt_{table}.csv")
        actual = {(r["ImageNumber"], r["ObjectNumber"]): r for r in read_csv(features / f"{table}.csv")}
        assert sorted(actual) == sorted((r["CPNF_GlobalImageNumber"], r["ObjectNumber"]) for r in expected)
        for row in expected:
            key = (row["CPNF_GlobalImageNumber"], row["ObjectNumber"])
            for column, value in row.items():
                if column.startswith(UNSTABLE_COLUMNS) or column == "CPNF_GlobalImageNumber":
                    continue
                assert float(actual[key][column]) == pytest.approx(
                    float(value), rel=FEATURE_RTOL, abs=1e-9, nan_ok=True
                ), f"{table}, image {key[0]}, object {key[1]}: {column}"


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
    features = tmp_path / "results" / "cellprofiler_tables"
    images = read_csv(features / "Image.csv")
    manifest = read_csv(features / "mask_manifest.csv")
    nuclei = read_csv(features / "Nuclei.csv")

    # Every image set appears once, with the reference object count, and with its plate.
    path_of = {row["ImageNumber"]: row["InputPath_DNA"] for row in manifest}
    counts = {path_of[row["ImageNumber"]]: float(row["Count_Nuclei"]) for row in images}
    assert counts == REFERENCE_COUNTS
    assert {path_of[row["ImageNumber"]].split("/")[0] == row["Metadata_Plate"] for row in images} == {True}
    assert {row["Metadata_Plate"] for row in nuclei} == {"plate1", "plate2"}

    # Object rows agree with the per-image counts, and every image set has both masks on disk.
    assert len(nuclei) == sum(REFERENCE_COUNTS.values())
    assert sorted(row["MaskObject"] for row in manifest) == ["Cells"] * 6 + ["Nuclei"] * 6
    for row in manifest:
        assert (tmp_path / "results" / row["MaskPath"]).is_file()
        assert "/work/" not in ",".join(row.values()), "manifest must not contain task work paths"

    # The masks of each plate are in <plate>/masks/.
    assert sorted({row["MaskPath"].split("/masks/")[0] for row in manifest}) == ["plate1", "plate2"]

    # Every feature value agrees with the reference tables.
    assert_features_match_reference(features)


def test_patch_prepares_the_analysis_pipeline_for_compartment_tables(tmp_path):
    """Check the analysis test pipeline: masks for 3 objects, and one table per object without a prefix.

    The pipeline extracts metadata (Well, Site) from the file names. The check of the new SaveImages modules
    then needs Java: before patch_cppipe.py started Java, it failed on such pipelines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result = patch(
        tmp_path,
        source=ROOT / "tests" / "test_analysis.cppipe",
        options="--objects Nuclei,Cells,Cytoplasm --illum-files",
    )
    assert result.returncode == 0, result.stderr[-3000:]

    # "Images only" would drop the .npy illumination functions of the file list.
    assert result.report["images_filter_changes"][0]["to"].endswith('(file does endwith ".npy")')
    assert [mask["object"] for mask in result.report["masks_managed"]] == ["Nuclei", "Cells", "Cytoplasm"]
    changes = result.report["export_changes"][0]["changes"]
    assert any(change.startswith("wants_prefix: True -> False") for change in changes)
    assert any(
        change.startswith("directory: 'Default Output Folder sub-folder|features'") for change in changes
    )
    assert any(change.startswith("add_metadata: False -> True") for change in changes)


def test_patch_checks_the_illumination_pipeline(tmp_path):
    """Check --illum: the illumination test pipeline passes, a pipeline without the calculation fails.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    good = patch(
        tmp_path, chunked=False, source=ROOT / "tests" / "test_illum.cppipe", options="--illum --no-masks"
    )
    assert good.returncode == 0, good.stderr[-3000:]
    assert [output["image"] for output in good.report["illum_outputs"]] == ["IllumDNA"]
    assert good.report["masks_added"] == [] and not good.report["export_added"]

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad = patch(bad_dir, chunked=False, options="--illum --no-masks")
    assert bad.returncode == 1
    assert "has no CorrectIlluminationCalculate module" in bad.stderr


def test_two_plates_with_illumination_end_to_end(tmp_path):
    """Run two plates with real CellProfiler: ILLUM per plate, chunks with the plate's functions, one merge.

    The 6 test images become 2 plates (PLATE_A, PLATE_B) of 3 sites, named like A01_s1_w1.tif, so that the
    test pipelines extract Well and Site.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    for number, plate in ((1, "PLATE_A"), (2, "PLATE_B")):
        folder = tmp_path / "img" / plate
        folder.mkdir(parents=True)
        for site, name in enumerate(("A01_s1_w1.tif", "A01_s2_w1.tif", "A02_s1_w1.tif")):
            shutil.copyfile(
                ROOT / "tests" / "images" / f"plate{number}" / f"site{site}_DNA.tif", folder / name
            )

    result = subprocess.run(
        [
            *("nextflow", "-log", str(tmp_path / "nextflow.log"), "run", str(ROOT), "-profile", "docker"),
            *("-work-dir", str(tmp_path / "work"), "--outdir", str(tmp_path / "results")),
            *("--pipeline", str(ROOT / "tests" / "test_analysis.cppipe")),
            *("--illum_pipeline", str(ROOT / "tests" / "test_illum.cppipe")),
            *("--input_dir", str(tmp_path / "img"), "--group_regex", r"^(.+?_s\d+)_w\d", "--chunk_size", "2"),
            *("--required_metadata", "Plate,Well,Site", "--total_cpus", "4", "--max_memory", "6.GB"),
        ],
        cwd=tmp_path,
        env=nextflow_env(),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    assert result.returncode == 0, result.stdout[-3000:]
    results = tmp_path / "results"

    # One illumination function per plate, finite and > 0 (check_illum.py), in <plate>/illum/.
    for plate in ("PLATE_A", "PLATE_B"):
        assert (results / plate / "illum" / "IllumDNA.npy").is_file()
        qc = json.loads((results / "logs" / f"qc_illum_{plate}.json").read_text())
        assert qc["errors"] == [] and qc["functions"]["IllumDNA.npy"]["min"] > 0

    # The merged tables: no prefix, ImageNumber 1-6 over both plates, and plate, well and site in every row.
    tables = results / "cellprofiler_tables"
    images = read_csv(tables / "Image.csv")
    cytoplasm = read_csv(tables / "Cytoplasm.csv")
    assert sorted(int(row["ImageNumber"]) for row in images) == [1, 2, 3, 4, 5, 6]
    assert sorted((row["Metadata_Plate"], row["Metadata_Well"], row["Metadata_Site"]) for row in images) == [
        (plate, well, site)
        for plate in ("PLATE_A", "PLATE_B")
        for well, site in (("A01", "1"), ("A01", "2"), ("A02", "1"))
    ]
    assert {row["Metadata_Plate"] for row in cytoplasm} == {"PLATE_A", "PLATE_B"}

    # Each chunk applied the function of its own plate: CellProfiler recorded the staged file of its job.
    assert {row["FileName_IllumDNA"] for row in images} == {"IllumDNA.npy"}

    # Masks of all three objects for each site, in <plate>/masks/.
    manifest = read_csv(tables / "mask_manifest.csv")
    assert len(manifest) == 6 * 3
    for row in manifest:
        assert row["MaskPath"].startswith(f"{row['Metadata_Plate']}/masks/")
        assert (results / row["MaskPath"]).is_file()

    # The tables join: each cytoplasm object with a parent finds its cell and its nucleus in the same image,
    # and each object row has the plate, well and site of its image. (The small test images also give some
    # cytoplasm objects without a parent: Parent_Cells 0.)
    cells = {(row["ImageNumber"], row["ObjectNumber"]) for row in read_csv(tables / "Cells.csv")}
    nuclei = {(row["ImageNumber"], row["ObjectNumber"]) for row in read_csv(tables / "Nuclei.csv")}
    with_parent = [row for row in cytoplasm if row["Parent_Cells"] != "0" and row["Parent_Nuclei"] != "0"]
    assert with_parent
    for row in with_parent:
        assert (row["ImageNumber"], row["Parent_Cells"]) in cells
        assert (row["ImageNumber"], row["Parent_Nuclei"]) in nuclei
    site_of = {
        row["ImageNumber"]: (row["Metadata_Plate"], row["Metadata_Well"], row["Metadata_Site"])
        for row in images
    }
    for row in cytoplasm:
        assert (row["Metadata_Plate"], row["Metadata_Well"], row["Metadata_Site"]) == site_of[
            row["ImageNumber"]
        ]
