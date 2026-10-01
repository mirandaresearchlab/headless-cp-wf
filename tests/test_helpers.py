import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"


def run_helper(name, *args, check=True):
    return subprocess.run(
        [sys.executable, str(BIN / name), *map(str, args)],
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

    entrypoint = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert 'nextflow run /opt/cp-headless -profile local "$@"' in entrypoint


def test_push_ci_runs_pre_commit_and_only_commits_tracked_fixes():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv run pre-commit run --all-files" in workflow
    assert "git add --update" in workflow
    assert "git add --all" not in workflow
    assert 'git push origin "HEAD:${BRANCH_NAME}"' in workflow
    assert 'exit "$status"' in workflow


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
