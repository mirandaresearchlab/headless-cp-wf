"""Tests of the helper scripts in bin/ (patch, check and merge steps), without CellProfiler.

Each test writes small CSV files that look like CellProfiler output into a temporary folder. Then it runs
one helper script as a separate program, and checks its output and its exit code. Exit code 0 means
"passed". Any other exit code means that the helper found a problem and would stop the job.
"""

import csv
import json
import os
import struct
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
        The command-line arguments. The function changes each one into text.
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

    # --plugins_dir defaults to cp-plugins/ of the workflow: without it, each run stops at the first check.
    assert "COPY cp-plugins/ ./cp-plugins/" in dockerfile

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


def read_rows(path):
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


def write_npy(path, values, shape, descr="<f8"):
    """Write a .npy file (format version 1.0) without numpy.

    The illumination check reads .npy files with the standard library only, so the tests write them the same
    way.

    Parameters
    ----------
    path : pathlib.Path
        The file to write. The function makes its folder if needed.
    values : list of float
        The values in C order.
    shape : tuple of int
        The shape of the array, for example (2, 2).
    descr : str, optional
        The numpy type string: "<f8" (the default) or "<f4".
    """
    header = f"{{'descr': '{descr}', 'fortran_order': False, 'shape': {tuple(shape)!r}, }}"
    header += " " * (63 - (10 + len(header)) % 64) + "\n"
    data = struct.pack(f"<{len(values)}{'d' if descr.endswith('8') else 'f'}", *values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin1") + data)


def test_merge_features_makes_image_numbers_unique_across_plates(tmp_path):
    """Check that the merge numbers the image sets of all chunks and plates 1, 2, 3.

    ImageNumber starts at 1 again in each chunk. Joins of the tables use ImageNumber, so the merge rewrites it
    and keeps the chunk-local value in CPNF_ChunkImageNumber.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    first = tmp_path / "features_P1_chunk_0001"
    second = tmp_path / "features_P2_chunk_0001"
    output = tmp_path / "merged"
    first.mkdir()
    second.mkdir()

    write_csv(first / "Image.csv", [["ImageNumber", "Count_Cells"], [1, 2], [2, 3]])
    write_csv(second / "Image.csv", [["ImageNumber", "Count_Cells"], [1, 4]])
    write_csv(first / "Cells.csv", [["ImageNumber", "ObjectNumber", "Area"], [1, 1, 10], [2, 1, 20]])
    write_csv(second / "Cells.csv", [["ImageNumber", "ObjectNumber", "Area"], [1, 1, 30]])

    run_helper("merge_features.py", "--outdir", output, first, second)

    rows = read_rows(output / "Cells.csv")
    assert [row["CPNF_Chunk"] for row in rows] == ["P1_chunk_0001", "P1_chunk_0001", "P2_chunk_0001"]
    assert [row["CPNF_ChunkImageNumber"] for row in rows] == ["1", "2", "1"]
    assert [row["ImageNumber"] for row in rows] == ["1", "2", "3"]
    assert "CPNF_GlobalImageNumber" not in rows[0]
    assert [row["ImageNumber"] for row in read_rows(output / "Image.csv")] == ["1", "2", "3"]

    report = json.loads((output / "merge_report.json").read_text(encoding="utf-8"))
    assert report["chunks"] == 2
    assert report["total_image_sets"] == 3


def test_merge_features_checks_unique_sites_only_in_image_tables(tmp_path):
    """Check that --unique-metadata ignores the mask list, which has one row per mask, not per site.

    Regression test: the merge counted the 2 mask rows of one site (Nuclei, Cells) as the same site twice.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    chunk = tmp_path / "features_P1_chunk_0001"
    chunk.mkdir()
    header = ["ImageNumber", "Metadata_Plate", "Metadata_Well", "Metadata_Site"]
    write_csv(chunk / "Image.csv", [header, [1, "P1", "A01", "1"]])
    write_csv(
        chunk / "mask_manifest.csv",
        [
            [*header, "MaskObject", "MaskPath"],
            [1, "P1", "A01", "1", "Nuclei", "P1/masks/a_Nuclei_mask.tiff"],
            [1, "P1", "A01", "1", "Cells", "P1/masks/a_Cells_mask.tiff"],
        ],
    )

    result = run_helper(
        "merge_features.py", "--outdir", tmp_path / "merged", "--unique-metadata", "Plate,Well,Site", chunk
    )
    assert "mask_manifest.csv: 2 rows" in result.stdout


def test_merge_features_rejects_rows_without_plate(tmp_path):
    """Check that --require-plate stops the merge if a row of an image or object table has no plate.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    chunk = tmp_path / "features_P1_chunk_0001"
    chunk.mkdir()
    write_csv(chunk / "Image.csv", [["ImageNumber", "Metadata_Plate"], [1, "P1"], [2, ""]])

    result = run_helper(
        "merge_features.py", "--outdir", tmp_path / "merged", "--require-plate", chunk, check=False
    )
    assert result.returncode != 0
    assert "Image.csv: 1 row(s) have no Metadata_Plate" in result.stderr


def compartment_chunk(folder, cytoplasm_header=None):
    """Write the Image, Cells, Nuclei and Cytoplasm tables (one image set, one cell) into a chunk folder.

    Parameters
    ----------
    folder : pathlib.Path
        The chunk folder to make, for example features_P1_chunk_0001.
    cytoplasm_header : list of str, optional
        Another header for Cytoplasm.csv, to test a missing join column.

    Returns
    -------
    pathlib.Path
        The chunk folder.
    """
    folder.mkdir()
    meta = ["Metadata_Plate", "Metadata_Well", "Metadata_Site"]
    ids = ["ImageNumber", "ObjectNumber", *meta, "Number_Object_Number"]
    write_csv(folder / "Image.csv", [["ImageNumber", *meta, "Count_Cells"], [1, "P1", "A01", 1, 1]])
    write_csv(folder / "Cells.csv", [[*ids, "AreaShape_Area"], [1, 1, "P1", "A01", 1, 1, 100]])
    write_csv(folder / "Nuclei.csv", [[*ids, "Parent_Cells"], [1, 1, "P1", "A01", 1, 1, 1]])
    header = cytoplasm_header or [*ids, "Parent_Cells", "Parent_Nuclei"]
    write_csv(folder / "Cytoplasm.csv", [header, [1, 1, "P1", "A01", 1, 1, 1, 1][: len(header)]])
    return folder


def test_merge_features_accepts_complete_compartment_tables(tmp_path):
    """Check that complete Image, Cells, Nuclei and Cytoplasm tables pass --check-compartments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    chunk = compartment_chunk(tmp_path / "features_P1_chunk_0001")
    run_helper("merge_features.py", "--outdir", tmp_path / "merged", "--check-compartments", chunk)
    assert (tmp_path / "merged" / "Cytoplasm.csv").is_file()


def test_merge_features_rejects_missing_join_column(tmp_path):
    """Check that a Cytoplasm table without Parent_Nuclei stops the merge.

    A join of the compartments links each cytoplasm row to its cell and its nucleus with Parent_Cells and
    Parent_Nuclei.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    header = ["ImageNumber", "ObjectNumber", "Metadata_Plate", "Metadata_Well", "Metadata_Site"]
    chunk = compartment_chunk(
        tmp_path / "features_P1_chunk_0001", [*header, "Number_Object_Number", "Parent_Cells"]
    )
    result = run_helper(
        "merge_features.py", "--outdir", tmp_path / "merged", "--check-compartments", chunk, check=False
    )
    assert result.returncode != 0
    assert "Cytoplasm.csv has no column(s) ['Parent_Nuclei']" in result.stderr


def test_merge_features_rejects_missing_compartment_table(tmp_path):
    """Check that the merge stops when a compartment table (here Cytoplasm.csv) is missing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    chunk = compartment_chunk(tmp_path / "features_P1_chunk_0001")
    (chunk / "Cytoplasm.csv").unlink()
    result = run_helper(
        "merge_features.py", "--outdir", tmp_path / "merged", "--check-compartments", chunk, check=False
    )
    assert result.returncode != 0
    assert "the merged tables lack ['Cytoplasm.csv']" in result.stderr


def run_check_illum(tmp_path, outputs, *extra):
    """Run check_illum.py on the illumination functions in tmp_path/out.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder with the out/ folder. The log, the report and the results go here too.
    outputs : int
        The number of SaveImages modules that save .npy files (the patch report lists them).
    *extra : str
        More options for check_illum.py.

    Returns
    -------
    subprocess.CompletedProcess
        The finished script. A failing script does not raise.
    """
    log = tmp_path / "log.txt"
    log.write_text("done\n", encoding="utf-8")
    report = tmp_path / "illum_patch_report.json"
    names = ["DNA", "RNA", "AGP", "Mito", "ER"][:outputs]
    report.write_text(
        json.dumps({"illum_outputs": [{"image": f"Illum{n}", "file_name": f"Illum{n}"} for n in names]}),
        encoding="utf-8",
    )
    return run_helper(
        "check_illum.py",
        *("--outdir", tmp_path / "out", "--log", log, "--patch-report", report),
        *("--dest", tmp_path / "illum", "--qc", tmp_path / "qc.json", *extra),
        check=False,
    )


def test_check_illum_accepts_one_positive_function_per_output(tmp_path):
    """Check that one finite, positive function per SaveImages module passes and is copied to --dest.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    write_npy(tmp_path / "out" / "IllumCorr" / "IllumDNA.npy", [1.0, 1.5, 2.0, 1.2], (2, 2))
    write_npy(tmp_path / "out" / "IllumCorr" / "IllumRNA.npy", [1.0, 1.1, 1.3, 1.0], (2, 2), "<f4")

    result = run_check_illum(tmp_path, 2, "--channels", 2)

    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (tmp_path / "illum").iterdir()) == ["IllumDNA.npy", "IllumRNA.npy"]
    qc = json.loads((tmp_path / "qc.json").read_text(encoding="utf-8"))
    assert qc["functions"]["IllumDNA.npy"]["min"] == 1.0
    assert qc["functions"]["IllumDNA.npy"]["max"] == 2.0
    assert qc["functions"]["IllumRNA.npy"]["shape"] == [2, 2]


def test_check_illum_rejects_a_missing_function(tmp_path):
    """Check that fewer .npy files than SaveImages modules stop the job.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    write_npy(tmp_path / "out" / "IllumDNA.npy", [1.0, 1.5], (1, 2))

    result = run_check_illum(tmp_path, 5)

    assert result.returncode == 1
    assert "found 1 illumination function(s) (.npy), expected 5" in result.stderr


def test_check_illum_rejects_values_that_are_not_finite_or_not_positive(tmp_path):
    """Check that NaN and values <= 0 stop the job: dividing an image by them gives wrong or infinite values.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    write_npy(tmp_path / "out" / "IllumDNA.npy", [1.0, float("nan")], (1, 2))
    write_npy(tmp_path / "out" / "IllumRNA.npy", [0.0, 1.0], (1, 2))

    result = run_check_illum(tmp_path, 2)

    assert result.returncode == 1
    assert "IllumDNA.npy: 1 value(s) are not finite" in result.stderr
    assert "IllumRNA.npy: minimum 0.0 is not > 0" in result.stderr


def test_check_illum_warns_when_functions_and_channels_differ(tmp_path):
    """Check that a different number of channels than functions gives a warning, not an error.

    A pipeline can calculate functions for some channels only, for example not for brightfield.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    write_npy(tmp_path / "out" / "IllumDNA.npy", [1.0, 1.5], (1, 2))

    result = run_check_illum(tmp_path, 1, "--channels", 2)

    assert result.returncode == 0, result.stderr
    assert "1 illumination function(s) for 2 channel(s)" in result.stderr


def test_check_chunk_adds_the_plate_to_every_table(tmp_path):
    """Check that --plate adds Metadata_Plate to the image table and to each object table.

    The merge and the joins of the tables need the plate in every row. The workflow knows it from the plate
    folder.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    output.mkdir()
    write_csv(output / "Image.csv", [["ImageNumber", "Count_Nuclei"], [1, 2]])
    write_csv(output / "Nuclei.csv", [["ImageNumber", "ObjectNumber", "Area"], [1, 1, 5], [1, 2, 6]])
    write_csv(output / "Experiment.csv", [["Key", "Value"], ["Version", "4.2.8"]])
    (tmp_path / "log.txt").write_text("done\n", encoding="utf-8")
    (tmp_path / "r.json").write_text("{}\n", encoding="utf-8")

    result = run_helper(
        "check_chunk.py",
        *("--outdir", output, "--log", tmp_path / "log.txt", "--patch-report", tmp_path / "r.json"),
        *("--input-dir", tmp_path / "input", "--features-dir", tmp_path / "features"),
        *("--manifest", tmp_path / "features" / "m.csv", "--qc", tmp_path / "qc.json", "--plate", "P1"),
        check=False,
    )

    assert result.returncode == 0, result.stderr
    image = read_rows(tmp_path / "features" / "Image.csv")
    nuclei = read_rows(tmp_path / "features" / "Nuclei.csv")
    assert [row["Metadata_Plate"] for row in image] == ["P1"]
    assert [row["Metadata_Plate"] for row in nuclei] == ["P1", "P1"]
    assert "Metadata_Plate" not in read_rows(tmp_path / "features" / "Experiment.csv")[0]


def test_check_chunk_rejects_another_plate_in_the_tables(tmp_path):
    """Check that a Metadata_Plate value from the pipeline that differs from the plate folder stops the chunk.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    rows = [["ImageNumber", "Metadata_Plate"], [1, "P2"]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--plate", "P1")
    assert result.returncode == 1
    assert "Image.csv: 1 row(s) have Metadata_Plate other than 'P1', e.g. 'P2'" in result.stderr


def test_check_chunk_skips_illumination_functions_in_the_mask_list(tmp_path):
    """Check that the staged .npy files are not channels of the mask list, and that masks get plate paths.

    NamesAndTypes records FileName_IllumDNA and PathName_IllumDNA. That folder is the job's illum/ folder, not
    a folder of input_dir.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    output = tmp_path / "chunk"
    input_dir = tmp_path / "input"
    illum = tmp_path / "illum"
    features = tmp_path / "features"
    (output / "masks" / "plate1").mkdir(parents=True)
    input_dir.mkdir()
    write_csv(
        output / "Image.csv",
        [
            ["ImageNumber", "FileName_DNA", "PathName_DNA", "FileName_IllumDNA", "PathName_IllumDNA"],
            [1, "site1_DNA.tif", input_dir / "plate1", "IllumDNA.npy", illum],
        ],
    )
    (output / "masks" / "plate1" / "site1_DNA_Nuclei_mask.tiff").touch()
    (tmp_path / "log.txt").write_text("done\n", encoding="utf-8")
    report = tmp_path / "patch_report.json"
    report.write_text(
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
        *("--outdir", output, "--log", tmp_path / "log.txt", "--patch-report", report),
        *("--expected-sets", 1, "--input-dir", input_dir, "--features-dir", features),
        *("--manifest", features / "mask_manifest.csv", "--qc", tmp_path / "qc.json", "--strict"),
        *("--plate", "plate1", "--illum-dir", illum),
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rows = read_rows(features / "mask_manifest.csv")
    assert [row["MaskPath"] for row in rows] == ["plate1/masks/site1_DNA_Nuclei_mask.tiff"]
    assert rows[0]["InputPath_DNA"] == "plate1/site1_DNA.tif"
    assert "InputPath_IllumDNA" not in rows[0]


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

    Otherwise one mask would replace the other when the workflow publishes the results.

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
    assert reader.fieldnames == ["CPNF_Chunk", "CPNF_ChunkImageNumber", "ImageNumber", "A", "B", "C"]
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

    The workflow processed such a site twice. Without --unique-metadata, the merge does not check it.

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
