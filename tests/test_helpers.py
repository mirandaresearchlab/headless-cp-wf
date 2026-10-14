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
    return subprocess.run(
        [HELPER_PYTHON, str(BIN / name), *map(str, args)],
        check=check,
        capture_output=True,
        text=True,
    )


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def test_dockerfile_runs_the_workflow_without_nested_docker():
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
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv run pre-commit run --all-files" in workflow
    assert "git add --update" in workflow
    assert "git add --all" not in workflow
    assert 'git push origin "HEAD:${BRANCH_NAME}"' in workflow
    assert 'exit "$status"' in workflow


def test_nextflow_stub_removes_its_generated_files(tmp_path):
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
    rows = [["ImageNumber", "Metadata_Plate", "Metadata_Well"], [1, "P1", "A01"], [2, "P1", "A02"]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--required-metadata", "Plate,Metadata_Well")
    assert result.returncode == 0, result.stderr


def test_check_chunk_rejects_missing_required_metadata_column(tmp_path):
    rows = [["ImageNumber", "Metadata_Plate"], [1, "P1"]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--required-metadata", "Plate,Well")
    assert result.returncode == 1
    assert "['Metadata_Well'] required by --required_metadata" in result.stderr


def test_check_chunk_rejects_empty_required_metadata(tmp_path):
    rows = [["ImageNumber", "Metadata_Plate", "Metadata_Well"], [1, "P1", "A01"], [2, "P1", ""]]
    result = run_check_chunk_on_image_table(tmp_path, rows, "--required-metadata", "Plate,Well")
    assert result.returncode == 1
    assert "1 image set(s) in Image.csv have empty" in result.stderr


def test_merge_features_rejects_same_site_in_two_chunks(tmp_path):
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
    output = tmp_path / "chunk"
    output.mkdir()
    write_csv(output / "Exp_Nuclei.csv", [["ImageNumber", "ObjectNumber"], [1, 1]])
    write_csv(output / "Exp_Image.csv", [["ImageNumber", "Count_Nuclei"], [1, "2.0"]])

    result = run_check_chunk_on_outdir(tmp_path, output)

    assert result.returncode == 1
    assert "counts 2 Nuclei objects but Exp_Nuclei.csv has 1 rows" in result.stderr
