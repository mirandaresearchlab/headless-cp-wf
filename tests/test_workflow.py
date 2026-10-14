"""Workflow-level tests: run main.nf with -stub-run (no CellProfiler) on small file trees.

These need Nextflow and Java 17-26. Run them with `uv run pytest -m workflow`.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TIFF = ROOT / "tests" / "images" / "plate1" / "site0_DNA.tif"

pytestmark = pytest.mark.workflow


def java_major(java):
    """Major version of a java binary, or None ('openjdk version "21.0.4"' -> 21)."""
    try:
        out = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=30).stderr
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r'version "(?:1\.)?(\d+)', out)
    return int(match.group(1)) if match else None


def supported_java_home(env):
    """A JAVA_HOME that Nextflow supports (Java 17-26): the selected one, else an installed one."""
    selected = env.get("JAVA_CMD") or (env.get("JAVA_HOME") and f"{env['JAVA_HOME']}/bin/java")
    selected = selected or shutil.which("java", path=env["PATH"])
    if selected and 17 <= (java_major(selected) or 0) <= 26:
        return None  # keep the user's choice
    candidates = []
    for major in (21, 17, 25, 24, 23, 22, 26, 20, 19, 18):
        if Path("/usr/libexec/java_home").exists():
            found = subprocess.run(
                ["/usr/libexec/java_home", "-v", str(major)], capture_output=True, text=True
            ).stdout.strip()
            candidates += [found] if found else []
        candidates += [f"/opt/homebrew/opt/openjdk@{major}", f"/usr/local/opt/openjdk@{major}"]
    candidates += sorted(str(path) for path in Path("/usr/lib/jvm").glob("*"))
    for home in candidates:
        if Path(home, "bin", "java").exists() and 17 <= (java_major(Path(home, "bin", "java")) or 0) <= 26:
            return home
    return None


def nextflow_env():
    env = os.environ.copy()
    # Nextflow from `uv sync` lives in .venv/bin, which is on PATH only inside `uv run` or an activated venv.
    venv_bin = ROOT / ".venv" / "bin"
    if not shutil.which("nextflow", path=env["PATH"]) and (venv_bin / "nextflow").exists():
        env["PATH"] = f"{venv_bin}{os.pathsep}{env['PATH']}"
    # Nextflow supports Java 17-26. Replace an unsupported JVM (for example Java 27) with an installed one.
    java_home = supported_java_home(env)
    if java_home:
        env["JAVA_HOME"] = java_home
        env.pop("JAVA_CMD", None)
        env["PATH"] = f"{Path(java_home, 'bin')}{os.pathsep}{env['PATH']}"
    env["NXF_ANSI_LOG"] = "false"
    return env


def make_images(root, names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TIFF, path)
    return root


def run_stub(tmp_path, input_dir, *args, outdir=None):
    if not shutil.which("nextflow", path=nextflow_env()["PATH"]):
        pytest.skip("nextflow is not installed (run ./scripts/bootstrap.sh)")
    outdir = outdir or tmp_path / "results"
    result = subprocess.run(
        [
            "nextflow",
            "-log",
            str(tmp_path / "nextflow.log"),
            "run",
            str(ROOT),
            "-profile",
            "local",
            "-stub-run",
            "-work-dir",
            str(tmp_path / "work"),
            "--pipeline",
            str(ROOT / "tests" / "test.cppipe"),
            "--input_dir",
            str(input_dir),
            "--outdir",
            str(outdir),
            *map(str, args),
        ],
        cwd=tmp_path,
        env=nextflow_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    result.log = (tmp_path / "nextflow.log").read_text(encoding="utf-8", errors="replace")
    return result


MULTI_CHANNEL = ["P1/A01_s1_w1.tif", "P1/A01_s1_w2.tif", "P1/A02_s1_w1.tif", "P1/A02_s1_w2.tif"]
GROUP_REGEX = r"^(.+?_s\d+)_w\d"


def test_complete_multichannel_sets_are_kept_together(tmp_path):
    images = make_images(tmp_path / "img", MULTI_CHANNEL)
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, "--chunk_size", 1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 image set(s), 4 file(s) -> 2 chunk(s)" in result.log
    assert "image sets have 2 file(s) each" in result.log


def test_image_set_with_missing_channel_fails(tmp_path):
    images = make_images(tmp_path / "img", [*MULTI_CHANNEL, "P1/A03_s1_w1.tif"])
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, "--chunk_size", 1)
    assert result.returncode != 0
    assert "1 image set(s) do not have 2 file(s)" in result.stdout + result.log
    assert "P1/A03_s1" in result.stdout + result.log


def test_file_not_matching_group_regex_fails(tmp_path):
    images = make_images(tmp_path / "img", [*MULTI_CHANNEL, "P1/A01_s1_thumb.tif"])
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX)
    assert result.returncode != 0
    assert "1 file(s) do not match --group_regex" in result.stdout + result.log


def test_allow_incomplete_sets_continues_with_warning(tmp_path):
    images = make_images(tmp_path / "img", [*MULTI_CHANNEL, "P1/A03_s1_w1.tif"])
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, "--allow_incomplete_sets", "true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Continuing because --allow_incomplete_sets is true" in result.log


def test_outdir_inside_input_dir_fails(tmp_path):
    images = make_images(tmp_path / "img", MULTI_CHANNEL)
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, outdir=images / "results")
    assert result.returncode != 0
    assert "is inside --input_dir" in result.stdout + result.log


def test_false_boolean_on_command_line_is_false(tmp_path):
    # Nextflow passes `--gzip_features false` as the string 'false'. Before boolParam() the
    # workflow treated it as true and wrote .csv.gz files.
    images = make_images(tmp_path / "img", ["a.tif", "b.tif"])
    result = run_stub(tmp_path, images, "--gzip_features", "false")
    assert result.returncode == 0, result.stdout + result.stderr
    features = tmp_path / "results" / "features"
    assert (features / "MyExpt_Image.csv").is_file()
    assert not list(features.glob("*.gz"))


def test_true_boolean_on_command_line_is_true(tmp_path):
    images = make_images(tmp_path / "img", ["a.tif", "b.tif"])
    result = run_stub(tmp_path, images, "--gzip_features", "true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "results" / "features" / "MyExpt_Image.csv.gz").is_file()


def test_invalid_boolean_fails(tmp_path):
    images = make_images(tmp_path / "img", ["a.tif"])
    result = run_stub(tmp_path, images, "--save_masks", "maybe")
    assert result.returncode != 0
    assert "--save_masks must be true or false" in result.stdout + result.log


def test_run_info_records_provenance(tmp_path):
    images = make_images(tmp_path / "img", ["a.tif"])
    result = run_stub(tmp_path, images, "--save_masks", "false")
    assert result.returncode == 0, result.stdout + result.stderr
    info = json.loads((tmp_path / "results" / "pipeline_info" / "run_info.json").read_text())
    assert info["workflow"]["name"] == "cp-headless"
    assert info["container"].startswith("cellprofiler/cellprofiler:4.2.8@sha256:")
    assert info["params"]["save_masks"] == "false"
    assert info["run"]["stub_run"] is True
    assert info["nextflow"]


FAKE_SBATCH = """#!/usr/bin/env bash
cat .command.run >> "$SBATCH_LOG"
echo "fake sbatch: refused" >&2
exit 1
"""
# Nextflow pulls the image with `apptainer pull --name <file> docker://...` before it submits a job.
FAKE_APPTAINER = """#!/usr/bin/env bash
if [ "$1" = pull ]; then
    while [ $# -gt 0 ]; do [ "$1" = --name ] && touch "$2"; shift; done
    exit 0
fi
echo "apptainer version 1.3.4"
"""


def run_with_fake_sbatch(tmp_path, *args, profile="slurm", params=(), home=None):
    """Run a cluster profile, where a fake sbatch records the job script and refuses the job.

    Returns (completed process, nextflow log, recorded job scripts).
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for name, text in (("sbatch", FAKE_SBATCH), ("apptainer", FAKE_APPTAINER)):
        (bin_dir / name).write_text(text, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    images = make_images(tmp_path / "img", ["a.tif"])
    env = nextflow_env()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SBATCH_LOG"] = str(tmp_path / "sbatch.log")
    if home:
        env.setdefault("NXF_HOME", str(Path(env["HOME"]) / ".nextflow"))
        env["HOME"] = str(home)
    result = subprocess.run(
        [
            *("nextflow", "-log", str(tmp_path / "nextflow.log"), *args, "run", str(ROOT)),
            *("-profile", profile, "-stub-run", "-work-dir", str(tmp_path / "work")),
            *("--pipeline", str(ROOT / "tests" / "test.cppipe"), "--input_dir", str(images)),
            *("--outdir", str(tmp_path / "results")),
            *map(str, params),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    log = (tmp_path / "nextflow.log").read_text(encoding="utf-8", errors="replace")
    jobs = tmp_path / "sbatch.log"
    return result, log, jobs.read_text(encoding="utf-8") if jobs.exists() else ""


def test_slurm_profile_without_account_adds_no_account(tmp_path):
    _, _, job = run_with_fake_sbatch(tmp_path)
    assert "#SBATCH" in job
    assert "--account" not in job


def test_slurm_settings_from_a_site_config_file_reach_the_job(tmp_path):
    site = tmp_path / "site.config"
    site.write_text(
        "params.slurm_account = 'naiss2026-1-1'\n"
        "params.slurm_partition = 'shared'\n"
        "params.slurm_cluster_options = '--qos=short'\n",
        encoding="utf-8",
    )
    _, _, job = run_with_fake_sbatch(tmp_path, "-c", str(site))
    assert "#SBATCH --account=naiss2026-1-1 --qos=short" in job
    assert "#SBATCH -p shared" in job


BERZELIUS = ("--slurm_account", "naiss2026-1-1", "--slurm_partition", "berzelius-cpu")


def test_berzelius_jobs_go_to_a_cpu_partition_with_local_scratch(tmp_path):
    cache = tmp_path / "containers"
    cache.mkdir()
    result, log, job = run_with_fake_sbatch(
        tmp_path, profile="berzelius", params=(*BERZELIUS, "--container_cache", cache)
    )
    assert "#SBATCH -p berzelius-cpu" in job, result.stdout + log
    assert "#SBATCH --account=naiss2026-1-1" in job
    assert "#SBATCH --mem 2048M" in job  # PATCH_PIPELINE: 1 core, at most 7 GB per core
    assert "nxf_mktemp /scratch/local" in job  # node-local NVMe
    assert "apptainer exec" in job and "docker run" not in job
    assert "--gpus" not in job and "gres" not in job
    assert list(cache.glob("cellprofiler-cellprofiler-4.2.8@sha256-*.img"))


def test_berzelius_without_account_stops_before_submitting(tmp_path):
    result, log, job = run_with_fake_sbatch(
        tmp_path, profile="berzelius", params=("--slurm_partition", "berzelius-cpu")
    )
    assert result.returncode != 0
    assert "-profile berzelius needs --slurm_account" in result.stdout + log
    assert job == ""


def test_berzelius_refuses_a_gpu_partition(tmp_path):
    result, log, job = run_with_fake_sbatch(
        tmp_path, profile="berzelius", params=("--slurm_account", "x", "--slurm_partition", "berzelius")
    )
    assert result.returncode != 0
    assert "CellProfiler uses only CPUs" in result.stdout + log
    assert job == ""


def test_berzelius_refuses_a_work_directory_in_home(tmp_path):
    # tmp_path becomes $HOME, so the work directory tmp_path/work is inside it.
    result, log, job = run_with_fake_sbatch(tmp_path, profile="berzelius", params=BERZELIUS, home=tmp_path)
    assert result.returncode != 0
    assert "is in your home directory" in result.stdout + log
    assert job == ""


def test_berzelius_settings_from_a_site_config_file(tmp_path):
    site = tmp_path / "berzelius-site.config"
    site.write_text(
        "params.slurm_account = 'naiss2026-1-1'\nparams.slurm_partition = 'berzelius-hopper-cpu'\n",
        encoding="utf-8",
    )
    result, log, job = run_with_fake_sbatch(tmp_path, "-c", str(site), profile="berzelius")
    assert "#SBATCH -p berzelius-hopper-cpu" in job, result.stdout + log
    assert "#SBATCH --account=naiss2026-1-1" in job
