"""Workflow-level tests: run main.nf with -stub-run (no CellProfiler) on small file trees.

These need Nextflow and Java 17-26. Run them with `uv run pytest -m workflow`.

Each test makes a small image folder (copies of one test image with new names), runs the real
main.nf with -stub-run, and checks the result or the error message. The stub blocks in main.nf make
fake outputs instead of running CellProfiler, so the tests check the grouping, the parameter checks
and the cluster job scripts in seconds.

The Slurm and Berzelius tests use a fake sbatch program. It saves the job script that Nextflow makes
and refuses the job, so the tests can read the #SBATCH lines without a cluster.
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

# All tests in this file carry the "workflow" mark, so plain `pytest` skips them (see pyproject.toml).
pytestmark = pytest.mark.workflow


def java_major(java):
    """Find the major version of a java program.

    Parameters
    ----------
    java : str or pathlib.Path
        Path of the java program.

    Returns
    -------
    int or None
        For example 21 for 'openjdk version "21.0.4"'. None if the program does not run.
    """
    try:
        out = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=30).stderr
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r'version "(?:1\.)?(\d+)', out)
    return int(match.group(1)) if match else None


def supported_java_home(env):
    """Find a JAVA_HOME that Nextflow supports (Java 17 to 26).

    Parameters
    ----------
    env : dict
        The environment of the test run (JAVA_CMD, JAVA_HOME and PATH are read).

    Returns
    -------
    str or None
        None if the selected Java is already supported. Else the folder of an installed,
        supported JDK, or None if there is none.
    """
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
    """Make the environment for a Nextflow run in a test.

    It puts the Nextflow of .venv on PATH if needed, replaces an unsupported Java, and turns off
    the colored log.

    Returns
    -------
    dict
        A copy of the current environment with these changes.
    """
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
    """Copy the test image to each name below a folder.

    Parameters
    ----------
    root : pathlib.Path
        The image folder to make.
    names : list of str
        The file names, relative to root. Sub-folders are made as needed.

    Returns
    -------
    pathlib.Path
        The image folder (root).
    """
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TIFF, path)
    return root


def run_stub(tmp_path, input_dir, *args, outdir=None):
    """Run main.nf with -profile local -stub-run on an image folder.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the work folder, the log and the results.
    input_dir : pathlib.Path
        The image folder.
    *args : object
        More options for `nextflow run`, for example "--chunk_size", 2.
    outdir : pathlib.Path, optional
        The output folder. The default is tmp_path / "results".

    Returns
    -------
    subprocess.CompletedProcess
        The finished Nextflow run. It also has the attribute ``log``: the Nextflow log as text.
    """
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


# Two sites with two channels each (w1, w2). GROUP_REGEX groups the files by the part before "_w".
MULTI_CHANNEL = ["P1/A01_s1_w1.tif", "P1/A01_s1_w2.tif", "P1/A02_s1_w1.tif", "P1/A02_s1_w2.tif"]
GROUP_REGEX = r"^(.+?_s\d+)_w\d"


def test_complete_multichannel_sets_are_kept_together(tmp_path):
    """Check that complete sites stay together: 4 files make 2 image sets in 2 chunks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", MULTI_CHANNEL)
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, "--chunk_size", 1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 image set(s), 4 file(s) -> 2 chunk(s)" in result.log
    assert "image sets have 2 file(s) each" in result.log


def test_image_set_with_missing_channel_fails(tmp_path):
    """Check that a site with only 1 of its 2 channels stops the run before CellProfiler starts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", [*MULTI_CHANNEL, "P1/A03_s1_w1.tif"])
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, "--chunk_size", 1)
    assert result.returncode != 0
    assert "1 image set(s) do not have 2 file(s)" in result.stdout + result.log
    assert "P1/A03_s1" in result.stdout + result.log


def test_file_not_matching_group_regex_fails(tmp_path):
    """Check that an extra file (here a thumbnail) that does not match group_regex stops the run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", [*MULTI_CHANNEL, "P1/A01_s1_thumb.tif"])
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX)
    assert result.returncode != 0
    assert "1 file(s) do not match --group_regex" in result.stdout + result.log


def test_allow_incomplete_sets_continues_with_warning(tmp_path):
    """Check that --allow_incomplete_sets true turns the error into a warning.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", [*MULTI_CHANNEL, "P1/A03_s1_w1.tif"])
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, "--allow_incomplete_sets", "true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Continuing because --allow_incomplete_sets is true" in result.log


def test_outdir_inside_input_dir_fails(tmp_path):
    """Check that an output folder inside the image folder stops the run.

    A later run would otherwise read the results as images.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", MULTI_CHANNEL)
    result = run_stub(tmp_path, images, "--group_regex", GROUP_REGEX, outdir=images / "results")
    assert result.returncode != 0
    assert "is inside --input_dir" in result.stdout + result.log


def test_false_boolean_on_command_line_is_false(tmp_path):
    """Check that `--gzip_features false` on the command line means false.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """

    # Nextflow passes `--gzip_features false` as the string 'false'. Before boolParam() the
    # workflow treated it as true and wrote .csv.gz files.
    images = make_images(tmp_path / "img", ["a.tif", "b.tif"])
    result = run_stub(tmp_path, images, "--gzip_features", "false")
    assert result.returncode == 0, result.stdout + result.stderr
    features = tmp_path / "results" / "features"
    assert (features / "MyExpt_Image.csv").is_file()
    assert not list(features.glob("*.gz"))


def test_true_boolean_on_command_line_is_true(tmp_path):
    """Check that `--gzip_features true` on the command line means true.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", ["a.tif", "b.tif"])
    result = run_stub(tmp_path, images, "--gzip_features", "true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "results" / "features" / "MyExpt_Image.csv.gz").is_file()


def test_invalid_boolean_fails(tmp_path):
    """Check that a boolean parameter with another value (here 'maybe') stops the run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", ["a.tif"])
    result = run_stub(tmp_path, images, "--save_masks", "maybe")
    assert result.returncode != 0
    assert "--save_masks must be true or false" in result.stdout + result.log


def test_run_info_records_provenance(tmp_path):
    """Check that run_info.json records the workflow, the pinned container and the parameters.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    images = make_images(tmp_path / "img", ["a.tif"])
    result = run_stub(tmp_path, images, "--save_masks", "false")
    assert result.returncode == 0, result.stdout + result.stderr
    info = json.loads((tmp_path / "results" / "pipeline_info" / "run_info.json").read_text())
    assert info["workflow"]["name"] == "cp-headless"
    assert info["container"].startswith("cellprofiler/cellprofiler:4.2.8@sha256:")
    assert info["params"]["save_masks"] == "false"
    assert info["run"]["stub_run"] is True
    assert info["nextflow"]


# The fake sbatch: save the job script that Nextflow made, then refuse the job (exit 1).
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

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the fake programs, the images, the work folder and the logs.
    *args : str
        Options for nextflow before "run", for example "-c", "site.config".
    profile : str, optional
        The Nextflow profile. The default is "slurm".
    params : tuple, optional
        More options for `nextflow run`, for example ("--slurm_account", "abc").
    home : pathlib.Path, optional
        A folder to use as $HOME for the run. The default keeps the real $HOME.

    Returns
    -------
    result : subprocess.CompletedProcess
        The finished Nextflow run.
    log : str
        The Nextflow log.
    jobs : str
        All job scripts that reached the fake sbatch ("" if none did).
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
    """Check that without --slurm_account the job script has no --account line.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    _, _, job = run_with_fake_sbatch(tmp_path)
    assert "#SBATCH" in job
    assert "--account" not in job


def test_slurm_settings_from_a_site_config_file_reach_the_job(tmp_path):
    """Check that settings from a -c config file reach the #SBATCH lines.

    Values in a -c file are read after the profiles, so the profile must read them lazily.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
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


# A valid account and CPU partition for the Berzelius tests.
BERZELIUS = ("--slurm_account", "naiss2026-1-1", "--slurm_partition", "berzelius-cpu")


def test_berzelius_jobs_go_to_a_cpu_partition_with_local_scratch(tmp_path):
    """Check the Berzelius job script: CPU partition, account, memory, /scratch/local, no GPU.

    PATCH_PIPELINE asks for 2 GB on 1 core, which is below 7 GB per core.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
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
    """Check that Berzelius without an account stops the run before any job goes to Slurm.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result, log, job = run_with_fake_sbatch(
        tmp_path, profile="berzelius", params=("--slurm_partition", "berzelius-cpu")
    )
    assert result.returncode != 0
    assert "-profile berzelius needs --slurm_account" in result.stdout + log
    assert job == ""


def test_berzelius_refuses_a_gpu_partition(tmp_path):
    """Check that Berzelius with a GPU partition stops the run before any job goes to Slurm.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    result, log, job = run_with_fake_sbatch(
        tmp_path, profile="berzelius", params=("--slurm_account", "x", "--slurm_partition", "berzelius")
    )
    assert result.returncode != 0
    assert "CellProfiler uses only CPUs" in result.stdout + log
    assert job == ""


def test_berzelius_refuses_a_work_directory_in_home(tmp_path):
    """Check that Berzelius with the work folder in $HOME (20 GB quota) stops the run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """

    # tmp_path becomes $HOME, so the work directory tmp_path/work is inside it.
    result, log, job = run_with_fake_sbatch(tmp_path, profile="berzelius", params=BERZELIUS, home=tmp_path)
    assert result.returncode != 0
    assert "is in your home directory" in result.stdout + log
    assert job == ""


def test_berzelius_settings_from_a_site_config_file(tmp_path):
    """Check that Berzelius settings from a -c config file reach the job script.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    site = tmp_path / "berzelius-site.config"
    site.write_text(
        "params.slurm_account = 'naiss2026-1-1'\nparams.slurm_partition = 'berzelius-hopper-cpu'\n",
        encoding="utf-8",
    )
    result, log, job = run_with_fake_sbatch(tmp_path, "-c", str(site), profile="berzelius")
    assert "#SBATCH -p berzelius-hopper-cpu" in job, result.stdout + log
    assert "#SBATCH --account=naiss2026-1-1" in job
