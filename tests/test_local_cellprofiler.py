"""Test that runs real CellProfiler without a container: the `local` profile.

This is the workstation mode without Docker. It needs `cellprofiler` (4.2.8, for example from the conda
environment of docs/how-to/run-without-docker.md) and Nextflow on PATH. Run it with
`uv run pytest -m local_cellprofiler`. Without `cellprofiler` on PATH, the test is skipped.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from test_cellprofiler import REFERENCE_COUNTS, ROOT, assert_features_match_reference, read_csv
from test_workflow import nextflow_env

pytestmark = pytest.mark.local_cellprofiler


def test_local_profile_end_to_end_matches_reference(tmp_path):
    """Run the test profile with CellProfiler from PATH, and compare the results with the Docker reference.

    The jobs get the Java of the CellProfiler environment (JAVA_HOME). Nextflow itself keeps its own Java.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary folder from pytest, removed after the test.
    """
    cellprofiler = shutil.which("cellprofiler")
    if not cellprofiler:
        pytest.skip("cellprofiler is not on PATH")
    java_home = Path(cellprofiler).resolve().parents[1] / "lib" / "jvm"
    local_config = tmp_path / "local.config"
    local_config.write_text(f"env.JAVA_HOME = '{java_home}'\n", encoding="utf-8")

    # The jobs run bin/*.py with the first python3 on PATH. It must be the Python of CellProfiler, not the
    # Python of .venv that `uv run` puts first.
    env = nextflow_env()
    env["PATH"] = f"{Path(cellprofiler).parent}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            "nextflow",
            "-log",
            str(tmp_path / "nextflow.log"),
            "run",
            str(ROOT),
            "-profile",
            "test,local",
            "-c",
            str(local_config),
            "-work-dir",
            str(tmp_path / "work"),
            "--outdir",
            str(tmp_path / "results"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, result.stdout[-3000:]

    # The same nuclei count in each image as in the official container.
    features = tmp_path / "results" / "features"
    manifest = read_csv(features / "mask_manifest.csv")
    path_of = {row["CPNF_GlobalImageNumber"]: row["InputPath_DNA"] for row in manifest}
    counts = {
        path_of[row["CPNF_GlobalImageNumber"]]: float(row["Count_Nuclei"])
        for row in read_csv(features / "MyExpt_Image.csv")
    }
    assert counts == REFERENCE_COUNTS
    assert len(read_csv(features / "MyExpt_Nuclei.csv")) == sum(REFERENCE_COUNTS.values())

    # Every feature value agrees with the reference of the official container, within FEATURE_RTOL.
    assert_features_match_reference(features)
