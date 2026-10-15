"""Tests that run real CellProfiler with rootless Docker and the rootless profile.

These need a rootless Docker daemon on Linux amd64 (CI starts one in the rootless job). Run them with
`uv run pytest -m rootless`. Without a rootless daemon, all tests of this file are skipped.
"""

import os
import shutil
import subprocess

import pytest
from test_cellprofiler import IMAGE, REFERENCE_COUNTS, ROOT, read_csv
from test_workflow import nextflow_env

pytestmark = pytest.mark.rootless


@pytest.fixture(scope="module", autouse=True)
def require_rootless_docker():
    """Skip all tests of this file unless Docker runs in rootless mode, and pull the image if needed.

    pytest runs this fixture once, before the first test of the file (autouse).
    """
    if not shutil.which("docker"):
        pytest.skip("docker is not on PATH")
    info = subprocess.run(
        ["docker", "info", "--format", "{{json .SecurityOptions}}"], capture_output=True, text=True
    )
    if info.returncode != 0:
        pytest.skip("the Docker daemon is not running")
    if "rootless" not in info.stdout:
        pytest.skip("the Docker daemon is not rootless")
    if os.getuid() == 0:
        pytest.skip("the tests must run as a normal user, not as root")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", IMAGE], check=True)


def owners(folder):
    """Find the files and folders below a folder that the current user does not own.

    Parameters
    ----------
    folder : pathlib.Path
        The folder to search, including the folder itself.

    Returns
    -------
    dict
        {path: numeric owner} for each path that belongs to another user. Empty if the user owns all.
    """
    found = {}
    for path in [folder, *folder.rglob("*")]:
        uid = path.lstat().st_uid
        if uid != os.getuid():
            found[str(path)] = uid
    return found


def test_non_root_user_in_container_writes_files_you_do_not_own(tmp_path):
    """Check the control: a job that runs as your own user ID inside the container makes foreign files.

    This is the problem that the rootless profile solves. If this test fails, the daemon does not map the
    user IDs like rootless Docker, and the ownership check of the end-to-end test proves nothing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o777)
    shared.chmod(0o777)  # mkdir applies the umask
    mount = ["docker", "run", "--rm", "--entrypoint", "", "-v", f"{shared}:{shared}"]
    made = subprocess.run(
        [*mount, "-u", f"{os.getuid()}:{os.getgid()}", IMAGE, "touch", f"{shared}/out.txt"],
        capture_output=True,
        text=True,
    )

    # The finally block removes the foreign file. Root inside the container is the test user, so it can.
    try:
        assert made.returncode == 0, made.stderr
        assert (shared / "out.txt").stat().st_uid != os.getuid()
    finally:
        subprocess.run([*mount, "-u", "0:0", IMAGE, "rm", "-f", f"{shared}/out.txt"], check=True)


def test_rootless_profile_end_to_end_matches_reference_and_you_own_the_files(tmp_path):
    """Run the test profile with the rootless profile, then check the results and the file owners.

    The nuclei counts must match the reference of test_cellprofiler.py. The user who started Nextflow
    must own every file in the results and in the work folder.

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
            "test,rootless",
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

    # The same biological results as with normal Docker.
    features = tmp_path / "results" / "features"
    images = read_csv(features / "MyExpt_Image.csv")
    manifest = read_csv(features / "mask_manifest.csv")
    path_of = {row["CPNF_GlobalImageNumber"]: row["InputPath_DNA"] for row in manifest}
    counts = {path_of[row["CPNF_GlobalImageNumber"]]: float(row["Count_Nuclei"]) for row in images}
    assert counts == REFERENCE_COUNTS
    assert len(read_csv(features / "MyExpt_Nuclei.csv")) == sum(REFERENCE_COUNTS.values())

    # The jobs ran as root inside the container, which is the test user on the host.
    assert owners(tmp_path / "results") == {}
    assert owners(tmp_path / "work") == {}
