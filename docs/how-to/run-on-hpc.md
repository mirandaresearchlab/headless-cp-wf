# Run on Berzelius

This guide uses the supplied Slurm profile. It requires an allocation and shared storage.

The cluster recipe was reviewed against configuration files but not executed on Berzelius.
Confirm account, partition, and launcher policy with the cluster administrator.

1. Make the repository, images, activated environment, and output paths accessible to all compute nodes.
2. Activate `cp-headless` and check that the Nextflow launcher uses a compatible Java.
3. Choose shared work and output folders with enough space.
4. Start Nextflow in a persistent session or an approved launcher job according to cluster policy.

Replace the uppercase tokens with real paths and your allocation account:

```bash
nextflow run . -profile berzelius \
  --images /SHARED/images --configs /SHARED/headless-cellprofiler/cp-configs \
  --outdir /SHARED/results --project screen01 \
  --shared_dir /SHARED/screen01-runtime \
  --slurm_account ACCOUNT
```

Expected behavior: Nextflow submits the five process types as Slurm jobs.
The default partition is `berzelius-cpu`. Confirm that this name is valid for your allocation.
`shared_dir` supplies `nextflow-work/` and `conda-cache/` below that directory.
You can instead set both `nf_work_dir` and `conda_cache` explicitly.
The Conda cache setting does not create an environment because tasks have no Conda directive.
The active Python and CellProfiler installation must be available to the jobs.

Defaults are 1 CPU, 6 GB, and 4 hours per job, with up to eight submitted jobs.
The profile retries statuses 137 and 143 twice. Other task failures terminate the run.
See [parameters](../reference/parameters.md) to change these values.

Slurm chooses job start times. A pending job is not necessarily a failure.
Keep the Nextflow launcher alive while it manages the jobs.
For resume, keep the same profile, shared paths, project, and relevant resource options.
See [resume instructions](../usage.md#resume-a-run).
