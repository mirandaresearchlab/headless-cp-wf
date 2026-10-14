"""Tests for scripts/berzelius/*: fake sbatch, squeue and nextflow record what the scripts do.

These tests need no cluster. Each fake program writes its folder and its arguments to <name>.args, so
a test can check how a script called it. The tests also check that wrong settings stop the scripts
before they submit anything.
"""

import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "berzelius"


def fake_bin(tmp_path, **programs):
    """Write fake programs that record their folder and arguments.

    Each program writes its working folder and its arguments to <tmp_path>/<name>.args, then runs
    its body.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder. The programs go into tmp_path / "fakebin".
    **programs : str
        The programs: name = bash code to run after the recording, for example
        sbatch="echo Submitted batch job 7".

    Returns
    -------
    pathlib.Path
        The folder with the fake programs (put it first on PATH).
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in programs.items():
        path = bin_dir / name
        path.write_text(
            f'#!/usr/bin/env bash\nprintf "%s\\n" "$PWD" "$@" > "{tmp_path}/{name}.args"\n{body}\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
    return bin_dir


def run(script, *args, env=None, cwd=None):
    """Run a script with bash.

    Parameters
    ----------
    script : pathlib.Path
        The script.
    *args : object
        The arguments of the script. The function changes each one into text.
    env : dict, optional
        The environment. The default is the current environment.
    cwd : pathlib.Path, optional
        The folder to start in. The default is the current folder.

    Returns
    -------
    subprocess.CompletedProcess
        The finished script. A failing script does not raise.
    """
    return subprocess.run(
        ["bash", str(script), *map(str, args)], capture_output=True, text=True, env=env, cwd=cwd
    )


def submit_env(tmp_path, bin_dir=None):
    """Make an environment with a temporary $HOME.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder. $HOME becomes tmp_path / "home".
    bin_dir : pathlib.Path, optional
        A folder with fake programs to put first on PATH. The default (None) changes no PATH.

    Returns
    -------
    dict
        A copy of the current environment with these changes.
    """
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    if bin_dir:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def inputs(tmp_path):
    """Make a fake /proj folder with a settings file and a params file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder. The fake project folder is tmp_path / "proj".

    Returns
    -------
    pathlib.Path
        The fake project folder.
    """
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "cp.env").write_text("export NXF_HOME=/proj/x NXF_APPTAINER_CACHEDIR=/proj/c\n")
    (proj / "params.yml").write_text("pipeline: a.cppipe\n")
    return proj


def submit_args(proj, system="ampere", run_dir=None):
    """Make the five required options of submit.sh.

    Parameters
    ----------
    proj : pathlib.Path
        The fake project folder (from inputs).
    system : str, optional
        The value of -s. The default is "ampere".
    run_dir : pathlib.Path, optional
        The value of -r. The default is proj / "runs" / "plate1".

    Returns
    -------
    tuple
        The options and their values, in the order of the command line.
    """
    return (
        *("-A", "naiss2026-1-1", "-s", system, "-e", proj / "cp.env", "-p", proj / "params.yml"),
        *("-r", run_dir or proj / "runs" / "plate1"),
    )


def test_submit_dry_run_uses_the_cpu_partition_of_each_system(tmp_path):
    """Check that -s ampere gives berzelius-cpu and -s hopper gives berzelius-hopper-cpu.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    proj = inputs(tmp_path)
    for system, partition in (("ampere", "berzelius-cpu"), ("hopper", "berzelius-hopper-cpu")):
        result = run(SCRIPTS / "submit.sh", *submit_args(proj, system), "-n", env=submit_env(tmp_path))
        assert result.returncode == 0, result.stderr
        command = shlex.split(result.stdout.split("would be:", 1)[1])
        assert command[:5] == ["sbatch", "-A", "naiss2026-1-1", "-p", partition]
        assert f"CPNF_RUN_DIR={proj / 'runs' / 'plate1'}" in command[9]


def test_submit_refuses_an_unknown_system(tmp_path):
    """Check that submit.sh refuses any other -s value (for example a GPU system).

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    proj = inputs(tmp_path)
    result = run(SCRIPTS / "submit.sh", *submit_args(proj, system="gpu"), env=submit_env(tmp_path))
    assert result.returncode == 2
    assert "CPU partitions only" in result.stderr


def test_submit_refuses_a_run_folder_in_home(tmp_path):
    """Check that submit.sh refuses a run folder in $HOME (20 GB quota on Berzelius).

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    proj = inputs(tmp_path)
    run_dir = tmp_path / "home" / "runs"
    result = run(SCRIPTS / "submit.sh", *submit_args(proj, run_dir=run_dir), env=submit_env(tmp_path))
    assert result.returncode == 2
    assert "is in your home directory" in result.stderr


def test_submit_refuses_a_missing_params_file(tmp_path):
    """Check that submit.sh refuses a params file that does not exist, before it calls sbatch.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    proj = inputs(tmp_path)
    (proj / "params.yml").unlink()
    result = run(SCRIPTS / "submit.sh", *submit_args(proj), env=submit_env(tmp_path))
    assert result.returncode == 2
    assert "params file not found" in result.stderr


def test_submit_calls_sbatch_with_the_head_job(tmp_path):
    """Check that submit.sh calls sbatch with the CPU partition, the head job and the extra options.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    proj = inputs(tmp_path)
    bin_dir = fake_bin(tmp_path, sbatch="echo Submitted batch job 7", squeue="true")
    env = submit_env(tmp_path, bin_dir)
    result = run(SCRIPTS / "submit.sh", *submit_args(proj), "--", "--chunk_size", "100", env=env)
    assert result.returncode == 0, result.stderr
    args = (tmp_path / "sbatch.args").read_text().splitlines()[1:]
    assert args[args.index("-p") + 1] == "berzelius-cpu"
    assert args[-3:] == [str(SCRIPTS / "run_nextflow.sbatch"), "--chunk_size", "100"]
    assert (proj / "runs" / "plate1" / "logs").is_dir()


def test_submit_refuses_a_second_head_job_in_the_same_run_folder(tmp_path):
    """Check that a running head job in the same run folder (seen by squeue) blocks a second one.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    proj = inputs(tmp_path)
    run_dir = proj / "runs" / "plate1"
    bin_dir = fake_bin(tmp_path, sbatch="exit 0", squeue=f'echo "cp-headless {run_dir}"')
    result = run(SCRIPTS / "submit.sh", *submit_args(proj), env=submit_env(tmp_path, bin_dir))
    assert result.returncode == 2
    assert "already runs" in result.stderr
    assert not (tmp_path / "sbatch.args").exists()


def head_job_env(tmp_path, partition):
    """Make the environment that Slurm and submit.sh give the head job.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder for the fake project folder and the fake programs.
    partition : str
        The partition of the fake job (SLURM_JOB_PARTITION).

    Returns
    -------
    env : dict
        The environment, with fake nextflow and apptainer programs first on PATH.
    run_dir : pathlib.Path
        The run folder of the fake job.
    """
    proj = inputs(tmp_path)
    run_dir = proj / "runs" / "plate1"
    run_dir.mkdir(parents=True)
    bin_dir = fake_bin(tmp_path, nextflow="exit 0", apptainer="exit 0")
    env = submit_env(tmp_path, bin_dir)
    env.update(
        CPNF_REPO=str(ROOT),
        CPNF_PARAMS=str(proj / "params.yml"),
        CPNF_RUN_DIR=str(run_dir),
        CPNF_ENV=str(proj / "cp.env"),
        SLURM_JOB_ID="99",
        SLURM_JOB_ACCOUNT="naiss2026-1-1",
        SLURM_JOB_PARTITION=partition,
    )
    return env, run_dir


def test_head_job_runs_nextflow_with_its_own_account_and_partition(tmp_path):
    """Check that the head job starts Nextflow in the run folder with -resume, account and partition.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    env, run_dir = head_job_env(tmp_path, "berzelius-hopper-cpu")
    result = run(SCRIPTS / "run_nextflow.sbatch", "--chunk_size", "50", env=env)
    assert result.returncode == 0, result.stderr
    cwd, *args = (tmp_path / "nextflow.args").read_text().splitlines()
    assert cwd == str(run_dir)  # the -resume cache lives in the run folder
    assert args[:4] == ["run", str(ROOT), "-profile", "berzelius"]
    assert "-resume" in args
    assert args[args.index("--slurm_account") + 1] == "naiss2026-1-1"
    assert args[args.index("--slurm_partition") + 1] == "berzelius-hopper-cpu"
    assert args[args.index("--container_cache") + 1] == "/proj/c"
    assert args[args.index("-with-trace") + 1] == "pipeline_info/trace_99.txt"
    assert args[-2:] == ["--chunk_size", "50"]


def test_head_job_stops_on_a_gpu_partition(tmp_path):
    """Check that a head job on a GPU partition stops before it starts Nextflow.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    env, _ = head_job_env(tmp_path, "berzelius")
    result = run(SCRIPTS / "run_nextflow.sbatch", env=env)
    assert result.returncode == 2
    assert "berzelius-cpu or berzelius-hopper-cpu" in result.stderr
    assert not (tmp_path / "nextflow.args").exists()


def test_smoke_test_refuses_to_run_on_a_login_node(tmp_path):
    """Check that smoke_test.sh stops outside a Slurm job (on a login node).

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    env = os.environ.copy()
    env.pop("SLURM_JOB_ID", None)
    result = run(SCRIPTS / "smoke_test.sh", tmp_path / "cp.env", tmp_path / "t", env=env)
    assert result.returncode == 2
    assert "not on a login node" in result.stderr
