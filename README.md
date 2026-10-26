# Headless CellProfiler

Run CellProfiler on microscopy plates with Nextflow to produce label masks and one combined table of cell measurements.

## Quick start

First install Nextflow and prepare the images using the [installation guide](docs/getting-started/installation.md).
Run these commands from the repository folder. This example requires the separate `test-images` dataset.
The full workflow example was not rerun during this documentation update.

```bash
conda env create -f environment.yml
conda activate cp-headless
nextflow run . -profile local --images test-images --configs cp-configs --project my_run
```

Results go to `projects/my_run/`, unless that name belongs to another run.
Nextflow prints the actual output path. Both supplied profiles preserve work files.

## Documentation

Start with the [documentation home](docs/index.md), [first run](docs/tutorials/first-run.md),
or [troubleshooting](docs/how-to/troubleshooting.md).
The MkDocs site includes job diagrams, setup, inputs, outputs, and generated reference pages.
See [preview and build instructions](docs/about/contributing.md).
A hosted documentation URL is not configured in this checkout.

## Citation

No project DOI or citation file is supplied. Record the code revision, pipeline files,
and environment versions used for your analysis. See [citation guidance](docs/about/citation.md).

## License

No license file is supplied in this checkout. Ask the maintainers about reuse permissions.
