#!/usr/bin/env bash

# Start the Docker service inside a lab workstation container (Docker in Docker), then test it.
# Run it as root in the workstation container, once after each start of the container:
#   bash scripts/start-docker-in-container.sh
# The guide is docs/how-to/run-with-docker.md. It also lists what the administrator must set up.
set -euo pipefail

# Stop with a message. Exit code 2 = the container cannot run Docker (an administrator must change it).
fail() {
    echo "ERROR: $*" >&2
    exit 2
}

[[ "$(id -u)" -eq 0 ]] || fail "run this script as root (the user of the workstation container)."
command -v dockerd >/dev/null || fail "Docker is not installed. Run: apt update && apt install -y docker.io"

# Docker is already running: nothing to do. Show which service answers. With setup B of the guide, it is the
# Docker service of the server, through its socket (/var/run/docker.sock).
if docker info >/dev/null 2>&1; then
    echo "Docker is already running: $(docker info --format 'host {{.Name}}, {{.OperatingSystem}}, version {{.ServerVersion}}')."
    exit 0
fi

# Docker needs all capabilities (the container must be started with --privileged). Without them, the
# Docker service stops with "iptables ... Permission denied" or "iptables failed".
# The test reads two of them: CAP_NET_ADMIN (bit 12, for the network) and CAP_SYS_ADMIN (bit 21, for mounts).
capabilities=$((16#$(awk '/^CapEff/ { print $2 }' /proc/self/status)))
if (((capabilities >> 12 & 1) == 0 || (capabilities >> 21 & 1) == 0)); then
    fail "this container is not privileged. The administrator must start it with --privileged."
fi

# Docker cannot store its images on the overlay file system of a container. Then the service starts, but
# each container fails with "failed to mount ... overlay". /var/lib/docker must be a volume.
mkdir -p /var/lib/docker
if [[ "$(stat -f -c %T /var/lib/docker)" == overlayfs ]]; then
    fail "/var/lib/docker is on the overlay file system of the container. The administrator must mount a volume
there, for example: docker run --privileged -v workstation-docker:/var/lib/docker ..."
fi

# cgroup v2: a cgroup can have processes or child groups with limits, not both. Move every process into the
# child group "init", then let the child groups use all controllers. Without this, each job with a memory
# or CPU limit (each Nextflow job) fails with "cannot enter cgroupv2 ... in an invalid state".
# This is the same fix as in the dind script of Docker. It runs while processes are still in the top group.
# (Read the files: cgroup files have size 0.) If a Docker service started without this script, it already
# turned on some controllers. Then the processes cannot move any more, and only a restart helps.
if [[ -f /sys/fs/cgroup/cgroup.controllers && -n "$(cat /sys/fs/cgroup/cgroup.procs)" ]]; then
    [[ -z "$(cat /sys/fs/cgroup/cgroup.subtree_control)" ]] ||
        fail "Docker was started without this script before. Restart the workstation container (ask the
administrator if you cannot), then run this script before any other Docker command."
    mkdir -p /sys/fs/cgroup/init
    xargs -rn1 </sys/fs/cgroup/cgroup.procs >/sys/fs/cgroup/init/cgroup.procs 2>/dev/null || :
    sed -e 's/ / +/g' -e 's/^/+/' </sys/fs/cgroup/cgroup.controllers >/sys/fs/cgroup/cgroup.subtree_control
fi

# A container has no systemd: start the service in the background, with its log in /var/log/dockerd.log.
nohup dockerd >/var/log/dockerd.log 2>&1 &
for _ in $(seq 60); do
    docker info >/dev/null 2>&1 && break
    sleep 1
done
docker info >/dev/null 2>&1 || {
    tail -5 /var/log/dockerd.log >&2
    fail "the Docker service did not start. Its log is /var/log/dockerd.log."
}

# Test it like a Nextflow job: a container with a memory and a CPU limit.
docker run --rm --memory 1g --cpus 1 hello-world >/dev/null ||
    fail "Docker started, but it cannot run a container with limits. See /var/log/dockerd.log."
echo "Docker runs: $(docker info --format 'version {{.ServerVersion}}, storage {{.Driver}}, cgroup v{{.CgroupVersion}}')"
