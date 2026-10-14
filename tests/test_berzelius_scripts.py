"""Tests for scripts/berzelius/*: fake sbatch, squeue and nextflow record what the scripts do."""

import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "berzelius"


def fake_bin(tmp_path, **programs):
    """Write fake programs that record their arguments to <tmp_path>/<name>.args."""
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
    return subprocess.run(
        ["bash", str(script), *map(str, args)], capture_output=True, text=True, env=env, cwd=cwd
    )


def submit_env(tmp_path, bin_dir=None):
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    if bin_dir:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return env


def inputs(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "cp.env").write_text("export NXF_HOME=/proj/x NXF_APPTAINER_CACHEDIR=/proj/c\n")
    (proj / "params.yml").write_text("pipeline: a.cppipe\n")
    return proj


def submit_args(proj, system="ampere", run_dir=None):
    return (
        *("-A", "naiss2026-1-1", "-s", system, "-e", proj / "cp.env", "-p", proj / "params.yml"),
        *("-r", run_dir or proj / "runs" / "plate1"),
    )


def test_submit_dry_run_uses_the_cpu_partition_of_each_system(tmp_path):
    proj = inputs(tmp_path)
    for system, partition in (("ampere", "berzelius-cpu"), ("hopper", "berzelius-hopper-cpu")):
        result = run(SCRIPTS / "submit.sh", *submit_args(proj, system), "-n", env=submit_env(tmp_path))
        assert result.returncode == 0, result.stderr
        command = shlex.split(result.stdout.split("would be:", 1)[1])
        assert command[:5] == ["sbatch", "-A", "naiss2026-1-1", "-p", partition]
        assert f"CPNF_RUN_DIR={proj / 'runs' / 'plate1'}" in command[9]


def test_submit_refuses_an_unknown_system(tmp_path):
    proj = inputs(tmp_path)
    result = run(SCRIPTS / "submit.sh", *submit_args(proj, system="gpu"), env=submit_env(tmp_path))
    assert result.returncode == 2
    assert "CPU partitions only" in result.stderr


def test_submit_refuses_a_run_folder_in_home(tmp_path):
    proj = inputs(tmp_path)
    run_dir = tmp_path / "home" / "runs"
    result = run(SCRIPTS / "submit.sh", *submit_args(proj, run_dir=run_dir), env=submit_env(tmp_path))
    assert result.returncode == 2
    assert "is in your home directory" in result.stderr


def test_submit_refuses_a_missing_params_file(tmp_path):
    proj = inputs(tmp_path)
    (proj / "params.yml").unlink()
    result = run(SCRIPTS / "submit.sh", *submit_args(proj), env=submit_env(tmp_path))
    assert result.returncode == 2
    assert "params file not found" in result.stderr


def test_submit_calls_sbatch_with_the_head_job(tmp_path):
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
    proj = inputs(tmp_path)
    run_dir = proj / "runs" / "plate1"
    bin_dir = fake_bin(tmp_path, sbatch="exit 0", squeue=f'echo "cp-headless {run_dir}"')
    result = run(SCRIPTS / "submit.sh", *submit_args(proj), env=submit_env(tmp_path, bin_dir))
    assert result.returncode == 2
    assert "already runs" in result.stderr
    assert not (tmp_path / "sbatch.args").exists()


def head_job_env(tmp_path, partition):
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
    env, _ = head_job_env(tmp_path, "berzelius")
    result = run(SCRIPTS / "run_nextflow.sbatch", env=env)
    assert result.returncode == 2
    assert "berzelius-cpu or berzelius-hopper-cpu" in result.stderr
    assert not (tmp_path / "nextflow.args").exists()


def test_smoke_test_refuses_to_run_on_a_login_node(tmp_path):
    env = os.environ.copy()
    env.pop("SLURM_JOB_ID", None)
    result = run(SCRIPTS / "smoke_test.sh", tmp_path / "cp.env", tmp_path / "t", env=env)
    assert result.returncode == 2
    assert "not on a login node" in result.stderr
