# Run with rootless Docker

This guide tells you how to run the workflow with **rootless Docker**. Rootless Docker runs the Docker service
as your own user, so you need no root rights to run containers. Use it on a shared server where you cannot
use `sudo`, and where an administrator did not install normal Docker for you.

!!! note "What the automatic test covers"
    On each push, the `rootless` job of the CI starts rootless Docker on a GitHub runner (Ubuntu, amd64) and
    runs step 4. It checks the nuclei counts and that the runner user owns all files. Your server can differ,
    for example in its cgroup settings or in the disk of the images. Run step 4 first. Tell us if a step does
    not work.

Berzelius has no Docker. On Berzelius, follow [Run on Berzelius](run-on-berzelius.md), which uses Apptainer.
Use this guide for other servers, for example a server of your group.

## What you need

| Need | How to check |
| --- | --- |
| A Linux server with an amd64 CPU. The CellProfiler 4.2.8 image exists only for Linux on amd64. | `uname -m` shows `x86_64`. |
| Rootless Docker, installed by you or by an administrator. | `docker info` shows `rootless` under `Security Options`. |
| Java 17 to 26 and Nextflow | `nextflow -version` |
| Space for the images. The Docker images are in your home folder by default. | `df -h ~` |

Ask the administrator of the server for these things. You cannot do them without root:

- The packages `docker-ce-rootless-extras` and `uidmap` (the programs `newuidmap` and `newgidmap`).
- A range of subordinate user IDs for you in `/etc/subuid` and `/etc/subgid`.
- Permission to keep your services running after you log out (`loginctl enable-linger $USER`). You need this
  for a long run that continues after you close the terminal.

!!! info "Before you start"
    This guide assumes that you cloned the repository, installed the tools and activated the environment.
    If you did not, do [Installation](../getting-started/installation.md) first. To check, open a terminal in the folder `headless-cp-wf`
    and run `source .venv/bin/activate` and then `nextflow -version`. It must print a version number.

## Step 1. Start your Docker service

Run these commands as your own user:

```bash
dockerd-rootless-setuptool.sh install
systemctl --user start docker
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker info | grep -i rootless
```

The last command must show a line with `rootless`. Put the `export DOCKER_HOST=...` line in your
`~/.bashrc`, or in your settings file, so that every new shell knows where your Docker service is.

If the server has no `systemd` user session, the installer shows the command to start the service by hand.

## Step 2. Move the images off a small home folder

Docker keeps its images in `~/.local/share/docker`. A CellProfiler image is large. If your home folder has a
small quota, or is on a network disk (NFS), store the images on a large local disk. Write
`~/.config/docker/daemon.json`. Write the real path. Docker does not expand variables such as `$USER`:

```json
{ "data-root": "/path/on/a/large/disk/docker-data" }
```

Then run `systemctl --user restart docker`. You must pull the images again after this change.

## Step 3. Use the `rootless` profile, not the `docker` profile

The `docker` profile of the workflow starts each job with `-u $(id -u):$(id -g)`. This is right for normal
Docker. It is wrong for rootless Docker. In rootless Docker, `root` (user 0) inside the container is
you on the server. Any other user ID inside the container is a different, high number on the server. Files
written by that user belong to a number that is not you, and you cannot always remove them.

The `rootless` profile turns on Docker and runs each job with `-u 0:0`, as `root` inside the container, which
is you on the server. Use `-profile rootless` instead of `-profile docker`.

!!! warning "Do not add `docker` after `rootless`"
    Nextflow applies the profiles in the order of the `-profile` option. With `-profile rootless,docker`, the
    `docker` profile sets `-u $(id -u):$(id -g)` again. You do not need the `docker` profile: `rootless` turns
    on Docker. If you must give both, give `docker,rootless`.

## Step 4. Test your setup

Do both tests before you run your data. First a dry run. The jobs make small fake files instead of running
CellProfiler, but Nextflow still starts each job in a container. Thus it tests your Docker service, the image
download and the file owner, and it takes a short time:

```bash
nextflow run . -profile test,rootless -stub-run
```

It must end with `[SUCCESS] completed=5 failed=0 cached=0`. If it fails, see the troubleshooting table below.
Then run the real test with CellProfiler:

```bash
nextflow run . -profile test,rootless
```

The test must give 6 image sets and 51 nuclei in `results/features/MyExpt_Image.csv` and
`results/features/MyExpt_Nuclei.csv`. See the [tutorial](../tutorials/first-run.md) for the expected output.
Check that your user owns the result files:

```bash
ls -l results/features
```

The owner must be you. If the owner is a number, the job did not run as `root` inside the container: check
that you used `-profile test,rootless` (step 3).

## Step 5. Run your data

Use the same options as in [Run on your data](../usage.md), with the `rootless` profile:

```bash
nextflow run . -profile rootless \
    --pipeline /path/to/analysis.cppipe \
    --input_dir /path/to/images \
    --outdir /path/to/results \
    --group_regex '^(.+?_s\d+)_w\d' \
    --max_cpus 8 --max_memory 32.GB
```

Set `--max_cpus` and `--max_memory` to the size that you may use on the server. Other users share it.

To use the [all-in-one image](use-container.md#the-all-in-one-image-nextflow-inside-the-container), remove the
`--user "$(id -u):$(id -g)"` line from its `docker run` command and use `--user 0:0` instead, for the same
reason as above.

## Troubleshooting

| Problem | Cause and solution |
| --- | --- |
| `Cannot connect to the Docker daemon` | Your shell does not know your service. Run `export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock` and `systemctl --user start docker`. |
| `newuidmap: command not found`, or `no subuid ranges found` | The administrator must install `uidmap` and add your user to `/etc/subuid` and `/etc/subgid`. |
| `permission denied` for `/var/run/docker.sock` | Your shell uses the normal Docker socket. Run `export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock`. |
| `could not get XDG_RUNTIME_DIR` | You are not in a normal login session, for example after `su`. Log in again with SSH. |
| `fork/exec /proc/self/exe: operation not permitted` | The server blocks user namespaces. The administrator must allow them. |
| The result files belong to a number, not to you | The job ran as another user inside the container. Use `-profile rootless` (step 3). To fix files that exist, run `docker run --rm -u 0:0 -v "$PWD:$PWD" alpine chown -R 0:0 "$PWD/results"`. These files then belong to you. |
| A job cannot write to a folder it needs | The job does not run as `root` inside the container. Use `-profile rootless`, and do not add `docker` after it. |
| A warning about the memory or CPU limits of a container | The kernel does not pass these limits to your service. The jobs still run, but Docker does not enforce the limits. Use `--max_cpus` and `--max_memory` to stay inside your share. |
| `no space left on device` while Docker pulls the image | The folder of Docker (`~/.local/share/docker`) is full. See step 2. |
| `exec format error` | The server is not amd64. The CellProfiler 4.2.8 image runs only on Linux amd64. |
| The run stops when you close the terminal | Start it inside `tmux` or `screen`, and ask the administrator to enable lingering for your user. |
