#!/bin/bash

# Berzelius preflight for cp-headless: shows the facts that submit.sh and your settings file need.
# Run it on a Berzelius login node. It only reads: it changes nothing.
# Usage: scripts/berzelius/preflight.sh [project-account] [/proj/<project>/users/$USER] [data dir ...]

# The two optional arguments. Any more arguments are data folders whose files it counts.
ACCT=${1:-}
PROJ=${2:-}
shift 2 2>/dev/null || true

# section: print a heading. have: true if a command exists (the script must also work off Berzelius).
section() { printf '\n=== %s ===\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Which system: the name of the login node tells Ampere or Hopper, and thus the CPU partition.
section "Host / system"
hostname
case "$(hostname)" in
  *hopper*) echo "Looks like HOPPER: CPU partition = berzelius-hopper-cpu, GPUs = H200" ;;
  *)        echo "Looks like AMPERE: CPU partition = berzelius-cpu, GPUs = A100 (-C fat for 80 GB)" ;;
esac

# Your projects and their accounts, and your storage use (space and number of files).
section "Projects (projinfo)"
if have projinfo; then projinfo; else echo "projinfo not found"; fi

section "Quotas (nscquota)"
if have nscquota; then nscquota; else echo "nscquota not found"; fi

# The partitions, and the state of the CPU nodes (how many, how many are free).
section "Partitions"
if have sinfo; then
  sinfo -s
  for p in berzelius-cpu berzelius-hopper-cpu; do
    sinfo -p "$p" -h -o '%P %a %l %D %t %c %m' 2>/dev/null | sed "s/^/  /"
  done
else echo "sinfo not found"; fi

# The limits of the account: partitions, QOS and maximum numbers of jobs.
if [ -n "$ACCT" ] && have sacctmgr; then
  section "Slurm association for account $ACCT"
  sacctmgr -n -P show assoc user="$USER" account="$ACCT" format=account,partition,qos,grptres,maxjobs,maxsubmit 2>/dev/null
fi

section "Your queued jobs"
have squeue && squeue -u "$USER" -o '%i %P %j %T %M %l %r' | head -20

# The software that the workflow needs: Apptainer, Java 17 to 26, Nextflow (or modules for them).
section "Software"
have apptainer && apptainer --version || echo "apptainer: not on PATH"
have java && java -version 2>&1 | head -1 || echo "java: not on PATH (Nextflow needs Java 17 to 26)"
have nextflow && nextflow -version 2>/dev/null | grep -i version || echo "nextflow: not on PATH"
if have module || type module >/dev/null 2>&1; then
  module avail nextflow 2>&1 | grep -iv '^$' | head -10
  module avail Miniforge3 2>&1 | grep -iv '^$' | head -5
fi

# $HOME has only 20 GB and 1 million files. Warn about caches that belong in /proj.
section "Home usage (20 GB / 1M files limit)"
du -sh "$HOME" 2>/dev/null
for d in .nextflow .apptainer .singularity .conda; do
  [ -e "$HOME/$d" ] && echo "WARNING: \$HOME/$d exists ($(du -sh "$HOME/$d" 2>/dev/null | cut -f1)) - move to /proj"
done

# The project folder: free space, and the number of files in the work folder, the image cache and
# the data folders. /proj allows 2 million files.
if [ -n "$PROJ" ]; then
  section "Project dir $PROJ"
  if [ -d "$PROJ" ]; then
    df -h "$PROJ" | tail -1
    for d in nf-work containers "$@"; do
      p="$d"; [ "${d#/}" = "$d" ] && p="$PROJ/$d"
      [ -d "$p" ] && printf '%-60s %10s files\n' "$p" "$(find "$p" -xdev -type f 2>/dev/null | wc -l)"
    done
  else
    echo "Not found: $PROJ"
  fi
fi

# The environment variables that the settings file must set.
section "Env vars"
for v in NXF_HOME NXF_APPTAINER_CACHEDIR APPTAINER_CACHEDIR TMPDIR; do
  printf '%-24s %s\n' "$v" "${!v:-<unset>}"
done

echo
echo "Next: write your settings file with scripts/berzelius/make_env.sh -p $PROJ, then run"
echo "scripts/berzelius/smoke_test.sh in an interactive CPU job (see docs/how-to/run-on-berzelius.md)."
