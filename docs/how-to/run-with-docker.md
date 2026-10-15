# Run with Docker

This guide shows how to run the workflow with Docker on a lab workstation. Each CellProfiler job then runs
in the official, pinned CellProfiler container. The workstation is an Ubuntu system where you are `root`,
for example the container that you reach with SSH on a lab server.

A lab workstation is often a container itself. Docker inside a container (Docker in Docker) works only if
the administrator of the server sets it up. Being `root` in the container is not enough.

!!! info "Before you start"
    Do [Installation](../getting-started/installation.md) first. This guide starts in the folder
    `headless-cp-wf`, after step 6 of that page.

!!! note "Testing status"
    On 2026-10-15 we ran the steps of this guide as `root` in Ubuntu 24.04 containers (amd64) on Docker
    Desktop. The test gave 6 image sets and 51 nuclei. We also checked the two failures that the
    administrator must prevent (see the table below). The CI job `workstation-docker` runs these steps on
    each push. We did not run them on a lab server. The host of the lab servers can have other limits.

## What the administrator must set up

Ask the administrator of the server for one of these two setups.

| Setup | What the administrator does | What you get |
| --- | --- | --- |
| **A. Docker inside the workstation** (tested) | Starts the workstation container with `--privileged` and with a volume on `/var/lib/docker`. | Your own Docker service and image storage. |
| **B. Docker service of the server** (tested on Docker Desktop) | Mounts the Docker socket of the server into the workstation (`-v /var/run/docker.sock:/var/run/docker.sock`). Mounts your data folders at the same path inside and outside. | The Docker service of the server, shared with other users. |

Example for setup A. The administrator runs this on the server, with the usual options of the workstation:

```bash
docker run -d --privileged -v <user>-docker:/var/lib/docker <usual options> <workstation image>
```

We tested these two failures in setup A:

| Missing part | What happens |
| --- | --- |
| No `--privileged` | The Docker service does not start: `iptables ... -N DOCKER` fails. |
| No volume on `/var/lib/docker` | The service starts, but each container fails: `failed to mount ... overlay`. Docker cannot store images on the overlay file system of a container. |

!!! warning "Security"
    Both setups give the workstation control of the server. A privileged container can change the server.
    The Docker socket gives `root` rights on the server. Give them only to trusted users. If the server runs
    rootless Docker, a privileged container has only the rights of the server user. We did not test this
    case.

## Step 1. Install Docker

```bash
apt update
apt install -y docker.io
```

This installs the Docker program and service from Ubuntu (version 29.1.3 in our test).

## Step 2. Start Docker

**Setup A.** A container has no `systemd`, so the service does not start by itself. Run this script after
each start of the workstation:

```bash
bash scripts/start-docker-in-container.sh
```

It must end with a line like `Docker runs: version 29.1.3, storage overlayfs, cgroup v2`. If Docker already
runs, the script shows which service answers and stops. The script checks
the setup first. If the container is not privileged, or `/var/lib/docker` has no volume, it stops with a
message for the administrator. It also applies a fix for cgroup v2: without it, every Nextflow job fails
with `cannot enter cgroupv2 ... in an invalid state`. The log of the service is `/var/log/dockerd.log`.

**Setup B.** Do not start a service. Check that the Docker service of the server answers:

```bash
docker info
```

## Step 3. Test: dry run

```bash
nextflow run . -profile test,docker -stub-run
```

It must show `6 image set(s), 6 file(s) -> 3 chunk(s)` and end without `ERROR`. In setup B, the
`headless-cp-wf` folder must also have the same path on the server. See step 5.

## Step 4. Test: real CellProfiler

```bash
nextflow run . -profile test,docker
```

The first run downloads the CellProfiler image. It needs about 5 GB of disk space. The run took 25 seconds
in our test. Check the tables:

```bash
python3 - <<'EOF'
import csv
f = "results_test/features/"
image = list(csv.DictReader(open(f + "MyExpt_Image.csv")))
nuclei = list(csv.DictReader(open(f + "MyExpt_Nuclei.csv")))
print("image sets:", len(image), "nuclei:", len(nuclei))
EOF
```

The output must be `image sets: 6 nuclei: 51`.

## Step 5. Run your images

Use `-profile docker` and the options of [Run on your data](../usage.md). First do a dry run to check your
`--group_regex`, then run the same command without `-stub-run`:

```bash
nextflow run . -profile docker -stub-run \
    --pipeline /path/to/analysis.cppipe \
    --input_dir /path/to/images \
    --outdir /path/to/results \
    --group_regex '^(.+?_s\d+)_w\d' \
    --max_cpus 8 --max_memory 32.GB
```

The `docker` profile runs each job as your user (`root` in the workstation), so you own the results.

**Setup B only.** The Docker service of the server mounts the folders of each job. It looks for them on the
server, not in your workstation. Thus the repository, the images, the work folder (`-work-dir`) and
`--outdir` must have the same path in the workstation and on the server. In our test, a work folder that
existed only in the workstation made the first job fail with exit status 125.

## The all-in-one image (optional)

The repository also has a `Dockerfile` for one image with Nextflow, Java and CellProfiler. Use it if you
want to run the whole workflow as one `docker run` command, without installing Nextflow. Inside the image,
the workflow uses the `local` profile:

```bash
docker build -t cp-headless:1.0.0 .
docker run --rm -v "$PWD:/workspace" cp-headless:1.0.0 \
    --pipeline /opt/cp-headless/tests/test.cppipe --input_dir /opt/cp-headless/tests/images \
    --outdir /workspace/results --group_regex '^(.+)$' --chunk_size 2 --max_cpus 2 --max_memory 3.GB
```

The run must give 6 image sets and 51 nuclei in `results/features/`. For your images, mount their folder,
for example `-v /data/images:/data/images:ro`, and use these paths in `--input_dir`. We tested this image on
a Mac with Docker Desktop, not on a lab server.

## Develop on a Mac

On a Mac with Docker Desktop, steps 3 to 5 also work. The Mac is for development only:

- The CellProfiler image exists only for amd64. On Apple Silicon, Docker Desktop emulates it, which is slower.
- Docker Desktop has its own memory limit (often 8 GB). A job that needs more stops with exit code 137.
  Raise *Memory* in *Settings > Resources*.
- Install Nextflow as in [Contributing](../about/contributing.md). If Nextflow reports `Cannot find Java`,
  select Java 21: `export JAVA_HOME=/opt/homebrew/opt/openjdk@21` and `unset JAVA_CMD`.

## Troubleshooting

| Message | Cause and solution |
| --- | --- |
| `docker: command not found` (exit status 127) | Docker is not installed. Do step 1. |
| `Cannot connect to the Docker daemon` | The service does not run. Setup A: run the script of step 2. Setup B: ask the administrator to mount the socket. |
| `this container is not privileged` (from the script) | Setup A needs `--privileged`. Ask the administrator. |
| `/var/lib/docker is on the overlay file system` (from the script) | Setup A needs a volume on `/var/lib/docker`. Ask the administrator. |
| `cannot enter cgroupv2 ... in an invalid state`, or `Docker was started without this script before` (from the script) | The Docker service started without the script of step 2, so it has no cgroup fix. The fix is possible only before the first start of Docker. Restart the workstation container (ask the administrator), then run the script of step 2 first. |
| The script says `Docker is already running: host <name>`, but you expect setup A | The server mounted its Docker socket into your workstation, so you use the Docker service of the server (setup B). Use the same paths as in step 5, or ask the administrator to remove the socket. |
| A job fails with exit status 125 in setup B | A folder of the job does not exist on the server. Use the same paths inside and outside (step 5). |
| Jobs stop with exit code 137 | Not enough memory. Lower `--max_memory`, or give Docker more memory. |
| Other errors | See [Troubleshooting](troubleshooting.md). |
