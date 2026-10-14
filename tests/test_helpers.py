"""Tests of the helper scripts in bin/ (patch, check and merge steps), without CellProfiler.

Each test writes small CSV files that look like CellProfiler output into a temporary folder, runs one
helper script as a separate program, and checks its output and its exit code. Exit code 0 means
"passed", and any other exit code means that the helper found a problem and would stop the job.
"""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"

# The helpers run inside the CellProfiler container (Python 3.8 for CellProfiler 4.2.8).
# scripts/test-helpers-py38.sh sets this to run every helper test on that interpreter too.
HELPER_PYTHON = os.environ.get("CPNF_HELPER_PYTHON") or sys.executable


def run_helper(name, *args, check=True):
    """Run a script from bin/ as a separate program, with HELPER_PYTHON.

    Parameters
    ----------
    name : str
        File name of the script, for example "check_chunk.py".
    *args : object
        The command-line arguments. Each one is converted to text.
    check : bool, optional
        If True (the default), a script that fails makes the test fail.

    Returns
    -------
    subprocess.CompletedProcess
        The finished script, with its exit code, stdout and stderr.
    """
    return subprocess.run(
        [HELPER_PYTHON, str(BIN / name), *map(str, args)],
        check=check,
        capture_output=True,
        text=True,
    )


def write_csv(path, rows):
    """Write rows to a CSV file.

    Parameters
    ----------
    path : pathlib.Path
        The file to write.
    rows : list of list
        The rows. The first row is the header.
    """
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def test_dockerfile_runs_the_workflow_without_nested_docker():
    """Check that the all-in-one image runs the workflow with the local profile.

    Thus the image never needs the Docker socket of the host.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM cellprofiler/cellprofiler:${CELLPROFILER_VERSION}" in dockerfile
    assert "JAVA_CMD=/opt/nextflow-java/bin/java" in dockerfile
    assert 'ENTRYPOINT ["cp-headless"]' in dockerfile
    assert "/var/run/docker.sock" not in dockerfile

    # nextflow.config includes conf/*.config: the image fails to parse its config without them.
    assert "COPY conf/ ./conf/" in dockerfile

    entrypoint = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert 'nextflow run /opt/cp-headless -profile local "$@"' in entrypoint


def test_push_ci_runs_pre_commit_and_only_commits_tracked_fixes():
    """Check that the CI bot commits only corrections to tracked files.

    The CI job must also fail when a check cannot be corrected.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv run pre-commit run --all-files" in workflow
    assert "git add --update" in workflow
    assert "git add --all" not in workflow
    assert 'git push origin "HEAD:${BRANCH_NAME}"' in workflow
    assert 'exit "$status"' in workflow


def test_nextflow_stub_removes_its_generated_files(tmp_path):
    """Check that scripts/test-nextflow.sh leaves no files behind.

    A fake nextflow program records its options and makes some files.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    bin_dir = tmp_path / "bin"
    temp_dir = tmp_path / "tmp"
    bin_dir.mkdir()
    temp_dir.mkdir()
    invocation = tmp_path / "nextflow-arguments.txt"
    fake_nextflow = bin_dir / "nextflow"
    fake_nextflow.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" > "$STUB_INVOCATION"
run_dir="$(dirname "$2")"
mkdir -p "$run_dir/work" "$run_dir/results" "$run_dir/.nextflow"
touch "$run_dir/generated-file"
""",
        encoding="utf-8",
    )
    fake_nextflow.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{environment['PATH']}",
            "STUB_INVOCATION": str(invocation),
            "TMPDIR": str(temp_dir),
        }
    )
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "test-nextflow.sh")],
        check=True,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    arguments = invocation.read_text(encoding="utf-8")
    assert "-work-dir" in arguments
    assert "--outdir" in arguments
    assert list(temp_dir.glob("cp-headless-stub.*")) == []


def test_merge_features_adds_stable_global_image_numbers(tmp_path):
    """Check that the merge numbers the image sets of all chunks 1, 2, 3.

    ImageNumber starts at 1 again in each chunk, so the merge adds CPNF_GlobalImageNumber.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    first = tmp_path / "features_chunk_0001"
    second = tmp_path / "features_chunk_0002"
    output = tmp_path / "merged"
    first.mkdir()
    second.mkdir()

    write_csv(first / "Experiment_Image.csv", [["ImageNumber", "Count_Cells"], [1, 2], [2, 3]])
    write_csv(second / "Experiment_Image.csv", [["ImageNumber", "Count_Cells"], [1, 4]])
    write_csv(
        first / "Experiment_Cells.csv",
        [["ImageNumber", "ObjectNumber", "Area"], [1, 1, 10], [2, 1, 20]],
    )
    write_csv(
        second / "Experiment_Cells.csv",
        [["ImageNumber", "ObjectNumber", "Area"], [1, 1, 30]],
    )

    run_helper("merge_features.py", "--outdir", output, first, second)

    with (output / "Experiment_Cells.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["CPNF_Chunk"] for row in rows] == ["chunk_0001", "chunk_0001", "chunk_0002"]
    assert [row["CPNF_GlobalImageNumber"] for row in rows] == ["1", "2", "3"]

    report = json.loads((output / "merge_report.json").read_text(encoding="utf-8"))
    assert report["chunks"] == 2
    assert report["total_image_sets"] == 3


def test_check_chunk_copies_tables_and_writes_qc(tmp_path):
    """Check a good chunk without masks: tables copied, empty mask list, no errors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    features = tmp_path / "features"
    output.mkdir()
    write_csv(output / "Experiment_Image.csv", [["ImageNumber", "Count_Cells"], [1, 2]])
    log = tmp_path / "cellprofiler.log"
    log.write_text("CellProfiler completed successfully\n", encoding="utf-8")
    patch_report = tmp_path / "patch_report.json"
    patch_report.write_text('{"masks_added": []}\n', encoding="utf-8")
    qc = tmp_path / "qc.json"
    manifest = features / "mask_manifest.csv"

    result = run_helper(
        "check_chunk.py",
        "--outdir",
        output,
        "--log",
        log,
        "--patch-report",
        patch_report,
        "--expected-sets",
        1,
        "--input-dir",
        tmp_path / "input",
        "--features-dir",
        features,
        "--manifest",
        manifest,
        "--qc",
        qc,
        "--strict",
    )

    assert "OK: 1 image sets" in result.stdout
    assert (features / "Experiment_Image.csv").is_file()
    assert manifest.read_text(encoding="utf-8") == "ImageNumber,MaskObject,MaskPath\n"
    assert json.loads(qc.read_text(encoding="utf-8"))["errors"] == []


def test_check_chunk_builds_mask_manifest_with_channel_paths(tmp_path):
    """Check that the mask list connects each mask to its image set.

    The input paths in the list are relative to input_dir.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    input_dir = tmp_path / "input"
    features = tmp_path / "features"
    mask_dir = output / "masks" / "plate1"
    mask_dir.mkdir(parents=True)
    input_dir.mkdir()
    write_csv(
        output / "Experiment_Image.csv",
        [
            [
                "ImageNumber",
                "Metadata_Plate",
                "FileName_DNA",
                "PathName_DNA",
                "FileName_Actin",
                "PathName_Actin",
            ],
            [
                1,
                "plate1",
                "site1_DNA.tif",
                input_dir / "plate1",
                "site1_Actin.tif",
                input_dir / "plate1",
            ],
        ],
    )
    (mask_dir / "site1_DNA_Nuclei_mask.tiff").touch()
    (mask_dir / "site1_DNA_Cells_mask.tiff").touch()
    log = tmp_path / "cellprofiler.log"
    log.write_text("CellProfiler completed successfully\n", encoding="utf-8")
    patch_report = tmp_path / "patch_report.json"
    patch_report.write_text(
        json.dumps(
            {
                "mask_reference_image": "DNA",
                "masks_added": [
                    {"object": "Nuclei", "suffix": "_Nuclei_mask", "format": "tiff"},
                    {"object": "Cells", "suffix": "_Cells_mask", "format": "tiff"},
                ],
            }
        ),
        encoding="utf-8",
    )
    qc = tmp_path / "qc.json"
    manifest = features / "mask_manifest.csv"

    run_helper(
        "check_chunk.py",
        "--outdir",
        output,
        "--log",
        log,
        "--patch-report",
        patch_report,
        "--expected-sets",
        1,
        "--input-dir",
        input_dir,
        "--features-dir",
        features,
        "--manifest",
        manifest,
        "--qc",
        qc,
        "--strict",
    )

    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["MaskObject"] for row in rows] == ["Nuclei", "Cells"]
    assert rows[0]["InputPath_DNA"] == "plate1/site1_DNA.tif"
    assert rows[0]["InputPath_Actin"] == "plate1/site1_Actin.tif"
    assert rows[0]["MaskPath"] == "masks/plate1/site1_DNA_Nuclei_mask.tiff"
    assert json.loads(qc.read_text(encoding="utf-8"))["mask_manifest_rows"] == 2


def test_merge_features_rejects_mask_path_collisions(tmp_path):
    """Check that the merge stops when two chunks have the same mask path.

    Otherwise one mask would overwrite the other when the results are published.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    first = tmp_path / "features_chunk_0001"
    second = tmp_path / "features_chunk_0002"
    output = tmp_path / "merged"
    first.mkdir()
    second.mkdir()
    header = ["ImageNumber", "MaskObject", "MaskPath"]
    write_csv(first / "mask_manifest.csv", [header, [1, "Nuclei", "masks/plate1/shared.tiff"]])
    write_csv(second / "mask_manifest.csv", [header, [1, "Nuclei", "masks/plate1/shared.tiff"]])

    result = run_helper(
        "merge_features.py",
        "--outdir",
        output,
        first,
        second,
        check=False,
    )

    assert result.returncode != 0
    assert "mask path collision" in result.stderr


def test_check_chunk_rejects_two_image_sets_mapping_to_one_mask(tmp_path):
    """Check that two image sets with the same mask file stop the chunk.

    Otherwise one of the two masks would be lost.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    input_dir = tmp_path / "input"
    features = tmp_path / "features"
    mask_dir = output / "masks" / "plate1"
    mask_dir.mkdir(parents=True)
    input_dir.mkdir()
    write_csv(
        output / "Experiment_Image.csv",
        [
            ["ImageNumber", "FileName_DNA", "PathName_DNA"],
            [1, "shared_DNA.tif", input_dir / "plate1"],
            [2, "shared_DNA.tif", input_dir / "plate1"],
        ],
    )
    (mask_dir / "shared_DNA_Nuclei_mask.tiff").touch()
    log = tmp_path / "cellprofiler.log"
    log.write_text("CellProfiler completed successfully\n", encoding="utf-8")
    patch_report = tmp_path / "patch_report.json"
    patch_report.write_text(
        json.dumps(
            {
                "mask_reference_image": "DNA",
                "masks_managed": [{"object": "Nuclei", "suffix": "_Nuclei_mask", "format": "tiff"}],
            }
        ),
        encoding="utf-8",
    )

    result = run_helper(
        "check_chunk.py",
        "--outdir",
        output,
        "--log",
        log,
        "--patch-report",
        patch_report,
        "--expected-sets",
        2,
        "--input-dir",
        input_dir,
        "--features-dir",
        features,
        "--manifest",
        features / "mask_manifest.csv",
        "--qc",
        tmp_path / "qc.json",
        "--strict",
        check=False,
    )

    assert result.returncode != 0
    assert "Mask path collision" in result.stderr


def test_merge_features_unions_columns_in_first_seen_order(tmp_path):
    """Check that the merged table has all columns of all chunks.

    The columns keep their first order, and missing values stay empty.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    first = tmp_path / "features_chunk_0001"
    second = tmp_path / "features_chunk_0002"
    first.mkdir()
    second.mkdir()
    write_csv(first / "Image.csv", [["ImageNumber", "A", "B"], [1, "a1", "b1"]])
    write_csv(second / "Image.csv", [["ImageNumber", "C", "A"], [1, "c2", "a2"]])

    run_helper("merge_features.py", "--outdir", tmp_path / "merged", first, second)

    with (tmp_path / "merged" / "Image.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == ["CPNF_Chunk", "CPNF_GlobalImageNumber", "ImageNumber", "A", "B", "C"]
    assert [(row["A"], row["B"], row["C"]) for row in rows] == [("a1", "b1", ""), ("a2", "", "c2")]


def run_check_chunk_on_image_table(tmp_path, rows, *extra):
    """Run check_chunk.py on a chunk that has only the given image table (no masks).

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the chunk, the log, the report and the outputs.
    rows : list of list
        The rows of the image table. The first row is the header.
    *extra : str
        More options for check_chunk.py, for example "--required-metadata", "Plate".

    Returns
    -------
    subprocess.CompletedProcess
        The finished script. A failing script does not raise.
    """
    output = tmp_path / "chunk"
    output.mkdir()
    write_csv(output / "Image.csv", rows)
    log = tmp_path / "cellprofiler.log"
    log.write_text("done\n", encoding="utf-8")
    patch_report = tmp_path / "patch_report.json"
    patch_report.write_text('{"masks_managed": []}\n', encoding="utf-8")
    features = tmp_path / "features"
    return run_helper(
        "check_chunk.py",
        "--outdir",
        output,
        "--log",
        log,
        "--patch-report",
        patch_report,
        "--input-dir",
        tmp_path / "input",
        "--features-dir",
        features,
        "--manifest",
        features / "mask_manifest.csv",
        "--qc",
        tmp_path / "qc.json",
        *extra,
        check=False,
    )


def test_check_chunk_accepts_complete_required_metadata(tmp_path):
    """Check that --required-metadata accepts names with and without the Metadata_ prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    rows = [["ImageNumber", "Metadata_Plate", "Metadata_Well"], [1, "P1", "A01"], [2, "P1", "A02"]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--required-metadata", "Plate,Metadata_Well")
    assert result.returncode == 0, result.stderr


def test_check_chunk_rejects_missing_required_metadata_column(tmp_path):
    """Check that a required metadata column that the pipeline does not make stops the chunk.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    rows = [["ImageNumber", "Metadata_Plate"], [1, "P1"]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--required-metadata", "Plate,Well")
    assert result.returncode == 1
    assert "['Metadata_Well'] required by --required_metadata" in result.stderr


def test_check_chunk_rejects_empty_required_metadata(tmp_path):
    """Check that an image set with an empty required metadata value stops the chunk.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    rows = [["ImageNumber", "Metadata_Plate", "Metadata_Well"], [1, "P1", "A01"], [2, "P1", ""]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--required-metadata", "Plate,Well")
    assert result.returncode == 1
    assert "1 image set(s) in Image.csv have empty" in result.stderr


def test_merge_features_rejects_same_site_in_two_chunks(tmp_path):
    """Check that the same plate, well and site in two chunks stops the merge.

    Such a site was processed twice. Without --unique-metadata, the merge does not check it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    first = tmp_path / "features_chunk_0001"
    second = tmp_path / "features_chunk_0002"
    first.mkdir()
    second.mkdir()
    header = ["ImageNumber", "Metadata_Plate", "Metadata_Well", "Metadata_Site"]
    write_csv(first / "Image.csv", [header, [1, "P1", "A01", "1"]])
    write_csv(second / "Image.csv", [header, [1, "P1", "A01", "1"]])

    result = run_helper(
        "merge_features.py",
        "--outdir",
        tmp_path / "merged",
        "--unique-metadata",
        "Plate,Well,Site",
        first,
        second,
        check=False,
    )
    assert result.returncode != 0
    assert "appears in chunk_0001 and in chunk_0002" in result.stderr

    # Without the option the merge keeps its old behaviour.
    run_helper("merge_features.py", "--outdir", tmp_path / "merged2", first, second)


def run_check_chunk_on_outdir(tmp_path, output):
    """Run check_chunk.py on a prepared CellProfiler output folder (no masks).

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the log, the report and the outputs.
    output : pathlib.Path
        The CellProfiler output folder with the CSV tables.

    Returns
    -------
    subprocess.CompletedProcess
        The finished script. A failing script does not raise.
    """
    log = tmp_path / "log.txt"
    log.write_text("done\n", encoding="utf-8")
    report = tmp_path / "patch_report.json"
    report.write_text('{"masks_managed": []}\n', encoding="utf-8")
    features = tmp_path / "features"
    return run_helper(
        "check_chunk.py",
        *("--outdir", output, "--log", log, "--patch-report", report, "--input-dir", tmp_path),
        *("--features-dir", features, "--manifest", features / "m.csv", "--qc", tmp_path / "qc.json"),
        check=False,
    )


def test_check_chunk_accepts_counts_that_match_object_tables(tmp_path):
    """Check that counts that agree with the object table pass.

    The image set without nuclei must be reported as a warning.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    output.mkdir()
    write_csv(output / "Exp_Nuclei.csv", [["ImageNumber", "ObjectNumber"], [1, 1], [1, 2], [2, 1]])
    rows = [["ImageNumber", "Count_Nuclei"], [1, "2.0"], [2, "1.0"], [3, "0.0"]]
    write_csv(output / "Exp_Image.csv", rows)

    result = run_check_chunk_on_outdir(tmp_path, output)

    assert result.returncode == 0, result.stderr
    qc = json.loads((tmp_path / "qc.json").read_text(encoding="utf-8"))
    assert qc["images_without_objects"] == {"Nuclei": 1}
    assert "1 of 3 image set(s) have no Nuclei objects" in result.stderr


def test_check_chunk_rejects_counts_that_disagree_with_object_table(tmp_path):
    """Check that a count that disagrees with the object table stops the chunk.

    Count_Nuclei says 2 objects, but the Nuclei table has 1 row: the export is incomplete.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    output.mkdir()
    write_csv(output / "Exp_Nuclei.csv", [["ImageNumber", "ObjectNumber"], [1, 1]])
    write_csv(output / "Exp_Image.csv", [["ImageNumber", "Count_Nuclei"], [1, "2.0"]])

    result = run_check_chunk_on_outdir(tmp_path, output)

    assert result.returncode == 1
    assert "counts 2 Nuclei objects but Exp_Nuclei.csv has 1 rows" in result.stderr
