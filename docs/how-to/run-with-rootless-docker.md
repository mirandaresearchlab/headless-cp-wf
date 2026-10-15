# Run with rootless Docker

This guide tells you how to run the workflow with **rootless Docker**. Rootless Docker runs the Docker service
as your own user, so you need no root rights to run containers. Use it on a shared server where you cannot
use `sudo`, and where an administrator did not install normal Docker for you.

!!! warning "Not tested"
    We did not run the workflow with rootless Docker. The steps follow the documentation of Docker and the
    behavior of the `docker` profile. Run the test in step 4 first. Tell us if a step does not work.

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

## Step 3. Make a settings file for rootless mode

The `docker` profile of the workflow starts each job with `-u $(id -u):$(id -g)`. This is right for normal
Docker. It is wrong for rootless Docker. In rootless Docker, `root` (user 0) inside the container is
you on the server. Any other user ID inside the container is a different, high number on the server. Files
written by that user belong to a number that is not you, and you cannot always remove them.

Write a small file `rootless.config`. It runs each job as `root` inside the container, which is you on the
server. It also replaces the `-u $(id -u):$(id -g)` option:

```groovy
// Root inside the container is you in rootless Docker. Do not run the job as another user.
docker.runOptions   = '--entrypoint "" -u 0:0'
docker.fixOwnership = false
```

Use `-u 0:0` and not just "no `-u` option". Some images set a non-root user, and then the job would not run as you.

## Step 4. Run the test

```bash
nextflow run . -profile test,docker -c rootless.config
```

The test must give 6 image sets and 51 nuclei in `results/features/MyExpt_Image.csv` and
`results/features/MyExpt_Nuclei.csv`. See the [tutorial](../tutorials/first-run.md) for the expected output.
Check that your user owns the result files:

```bash
ls -l results/features
```

The owner must be you. If the owner is a number, the job did not run as `root` inside the container: check the
config file.

## Step 5. Run your data

Use the same options as in [Run on your data](../usage.md), and add the profile and the config file:

```bash
nextflow run . -profile docker -c rootless.config \
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
| The result files belong to a number, not to you | The job ran as another user inside the container. Use `-c rootless.config` (step 3). To fix files that exist, run `docker run --rm -u 0:0 -v "$PWD:$PWD" alpine chown -R 0:0 "$PWD/results"`. These files then belong to you. |
| A job cannot write to a folder it needs | The job does not run as `root` inside the container. Check `-u 0:0` in `rootless.config`. |
| A warning about the memory or CPU limits of a container | The kernel does not pass these limits to your service. The jobs still run, but Docker does not enforce the limits. Use `--max_cpus` and `--max_memory` to stay inside your share. |
| `no space left on device` while Docker pulls the image | The folder of Docker (`~/.local/share/docker`) is full. See step 2. |
| `exec format error` | The server is not amd64. The CellProfiler 4.2.8 image runs only on Linux amd64. |
| The run stops when you close the terminal | Start it inside `tmux` or `screen`, and ask the administrator to enable lingering for your user. |
