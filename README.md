# cp-headless

Headless CellProfiler as a portable Nextflow DSL2 workflow. Provide a `.cppipe`/`.cpproj` and an image
folder to produce merged feature tables and uint16 segmentation masks for every object set, even when the
input pipeline does not save those masks itself.

## Repository layout

```text
.
├── main.nf                  DSL2 processes and entry workflow
├── nextflow.config          parameters, resources, profiles, and run reports
├── Dockerfile               complete Nextflow + CellProfiler runtime image
├── .dockerignore            excludes local state from Docker builds
├── .github/workflows/       push CI with pre-commit autofix
├── bin/                     executable Python helpers (automatically added to task PATH)
├── tests/
│   ├── images/              small smoke-test image set
│   ├── test.cppipe          smoke-test CellProfiler pipeline
│   └── test_helpers.py      Python helper tests
├── scripts/
│   ├── bootstrap.sh         creates the uv environment and installs pre-commit
│   ├── docker-entrypoint.sh Docker image launcher
│   └── test-nextflow.sh     runs the Nextflow stub test
├── pyproject.toml           Python development-tool configuration
├── uv.lock                  locked development dependencies
└── .pre-commit-config.yaml  automated lint, format, unit, and workflow checks
```

Nextflow automatically makes executable files under `bin/` available to process scripts. Keeping generated
data in `work/` and published data under `results/` follows Nextflow's separation of task state from outputs.

```
results/
├── features/              merged feature tables + mask_manifest.csv + merge_report.json
├── masks/                 <same sub-folders as input>/<image>_<Object>_mask.tiff  (0 = background, 1..N = objects)
├── cellprofiler_outputs/  anything else your own .cppipe saves (overlays, crops, ...), per chunk
├── pipeline/              patched.cppipe + patch_report.json (every change made to your pipeline)
├── logs/                  CellProfiler log + QC json per chunk
└── pipeline_info/         Nextflow timeline / report / trace
```

## Quick start

Runtime requirements:

- Nextflow 24.04 or newer and a supported Java runtime (Java 17–26 for the current Nextflow release);
- Docker (recommended), Singularity/Apptainer, or a local CellProfiler installation;
- enough disk space for the Nextflow `work/` directory and published results.

```bash
# Verify the workflow structure without running CellProfiler
nextflow run . -profile test,local -stub-run

# Run the bundled six-image smoke test with CellProfiler in Docker
nextflow run . -profile test,docker

# Run your own data
nextflow run . -profile docker \
    --pipeline   /path/to/analysis.cppipe \
    --input_dir  /path/to/images \
    --outdir     results \
    --max_cpus 8 --max_memory '32.GB'
```

The Docker profile pins CellProfiler to `cellprofiler/cellprofiler:4.2.8`. Change `--container` when the
`DateRevision` in your pipeline requires another version. The `local` profile expects `cellprofiler` on
`PATH`; it is mainly useful for development and the stub test.

## Run the entire workflow in Docker

This option packages Nextflow, Java 21, CellProfiler 4.2.8, and the workflow in one image. It runs the
workflow with the `local` profile inside the container, so it does not need Docker-in-Docker or access to the
host Docker socket.

The upstream CellProfiler 4.2.8 image is currently published for Linux AMD64. On Apple Silicon, include the
shown `--platform linux/amd64` option so Docker Desktop uses emulation.

```bash
# Build once from the repository root
docker build --platform linux/amd64 -t cp-headless:1.0.0 .

# Mount the current directory as the writable Nextflow workspace
docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    cp-headless:1.0.0 \
    --pipeline /workspace/analysis.cppipe \
    --input_dir /workspace/images \
    --outdir /workspace/results \
    --group_regex '^(.+_s\d+)_(?:DNA|Actin)\.tif$' \
    --chunk_size 50 \
    --max_cpus 8 \
    --max_memory 32.GB
```

The mounted workspace contains `work/`, `.nextflow/`, and the published results, allowing `-resume` to work
across container runs:

```bash
docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    cp-headless:1.0.0 \
    --pipeline /workspace/analysis.cppipe \
    --input_dir /workspace/images \
    --outdir /workspace/results \
    -resume
```

On Windows, omit `--user "$(id -u):$(id -g)"`. For data stored outside the current directory, mount it
read-only and use its container path:

```bash
docker run --rm --platform linux/amd64 \
    --user "$(id -u):$(id -g)" \
    -v "$PWD:/workspace" \
    -v /absolute/path/to/data:/data:ro \
    cp-headless:1.0.0 \
    --pipeline /data/analysis.cppipe \
    --input_dir /data/images \
    --outdir /workspace/results
```

Use `docker run --rm cp-headless:1.0.0 --help` to display the container-specific usage summary. This
whole-workflow image is separate from `nextflow run . -profile docker`: the latter runs Nextflow on the host
and starts a CellProfiler container for each task.

Use your own config file with `-c my.config`, or keep parameters in YAML with `-params-file params.yaml`:

```yaml
pipeline: /data/exp1/analysis.cppipe
input_dir: /data/exp1/images
chunk_size: 50
group_regex: '^(.+_s\d+)_w\d'
max_memory: 32.GB
```

Add `-resume` to rerun only what changed or failed. Use `-stub-run` to check the workflow wiring without
running CellProfiler.

## Development setup with uv

The workflow helper scripts use only Python's standard library at runtime. CellProfiler is supplied by the
configured container, so it is intentionally not installed into the development virtual environment. The
locked `uv` development group contains Ruff, pytest, and pre-commit.

```bash
# One-time setup. This creates .venv with the shell prompt "cp-headless",
# installs every locked dependency, and installs the Git pre-commit hook.
./scripts/bootstrap.sh

source .venv/bin/activate
# Your shell prompt now uses: (cp-headless)

# Reproduce the exact environment later
uv sync --locked --all-groups

# Run checks manually
uv run ruff check bin tests
uv run ruff format --check bin tests
uv run pytest
bash scripts/test-nextflow.sh
uv run pre-commit run --all-files
```

If you prefer the individual setup commands, use:

```bash
uv venv --python 3.12 --prompt cp-headless
uv sync --all-groups
uv run pre-commit install
```

`uv.lock` records all Python development dependencies and their transitive versions. Nextflow, Java, and the
chosen container engine are system/runtime tools rather than Python packages and therefore are not managed by
`uv`.

### Push CI and automatic formatting corrections

`.github/workflows/ci.yml` runs the complete pre-commit suite on every branch push. If Ruff or another
hook changes tracked files, CI reruns all hooks (up to three passes), commits the clean corrections as
`github-actions[bot]`, and pushes them to the same branch. If no hook can correct the problem, the hooks still
fail after correction, or GitHub cannot push the correction, the CI job fails.

The workflow has `contents: write` permission for this bot commit. A protected branch must allow GitHub Actions
to push, or the correction push will intentionally fail and require a developer to run the hooks locally:

```bash
uv run pre-commit run --all-files
git add --update
git commit -m "style: apply pre-commit corrections"
git push
```

## How it works

1. **PATCH_PIPELINE** loads your `.cppipe` with CellProfiler's own API. It stops immediately if the pipeline can't be loaded (for example, a missing plugin or a pipeline saved by a newer CellProfiler). It then:
   - adds `ConvertObjectsToImage (uint16)` and `SaveImages` for every object set that isn't already saved. Masks mirror your input folder structure and are **never overwritten**;
   - adds `ExportToSpreadsheet` if your pipeline has no spreadsheet export;
   - removes `CreateBatchFiles`, which would stop a headless run;
   - redirects outputs that point to absolute paths ("Elsewhere…") or to the input folder into the task's output folder.

   Every change is listed in `pipeline/patch_report.json`.
2. **CELLPROFILER** runs `cellprofiler -c -r --file-list` on each chunk of image sets. The input folder is linked in whole, so sub-folders and any metadata taken from folder names are preserved. `check_chunk.py` then fails the task if CellProfiler "succeeded" but produced no CSVs, zero image sets, missing masks, ambiguous mask mappings, or duplicate mask paths within a chunk. It also creates a per-chunk mask manifest from the actual files on disk.
3. **MERGE_FEATURES** combines each table across chunks into one file. `ImageNumber` restarts at 1 in every chunk, so two columns are added:
   - `CPNF_Chunk`: the chunk each row came from;
   - `CPNF_GlobalImageNumber`: a unique image number across the whole run.

   Join the per-image, per-object, and mask-manifest tables on `CPNF_GlobalImageNumber`. While merging,
   the workflow rejects any `MaskPath` produced by more than one chunk so publishing collisions cannot
   silently pass as a successful run.

## Mask manifest

`results/features/mask_manifest.csv` is a long-form table with one row per image set and mask object. Its
paths are relative to the run's input or output root, so they do not contain temporary Nextflow work paths.
For example:

```csv
CPNF_Chunk,CPNF_GlobalImageNumber,ImageNumber,Metadata_Plate,FileName_DNA,PathName_DNA,InputPath_DNA,FileName_Actin,PathName_Actin,InputPath_Actin,MaskObject,MaskPath
chunk_0001,1,1,plate1,site1_DNA.tif,plate1,plate1/site1_DNA.tif,site1_Actin.tif,plate1,plate1/site1_Actin.tif,Nuclei,masks/plate1/site1_DNA_Nuclei_mask.tiff
chunk_0001,1,1,plate1,site1_DNA.tif,plate1,plate1/site1_DNA.tif,site1_Actin.tif,plate1,plate1/site1_Actin.tif,Cells,masks/plate1/site1_DNA_Cells_mask.tiff
```

- `InputPath_<channel>` is relative to `--input_dir`.
- `MaskPath` is relative to `--outdir`.
- `MaskObject` identifies the CellProfiler object set, such as `Nuclei` or `Cells`.
- `Metadata_*`, `FileName_*`, and `PathName_*` columns come from the per-image CellProfiler table.
- `CPNF_GlobalImageNumber` is stable across chunks and joins the manifest to merged feature tables.

When `--gzip_features true` is used, the merged manifest is written as `mask_manifest.csv.gz`.

## Parameters

| Parameter | Default | Meaning |
|---|---|---|
| `pipeline` | — | `.cppipe` / `.cpproj` (required) |
| `input_dir` | — | Image folder, searched recursively; hidden files are skipped (required) |
| `outdir` | `results` | Output folder |
| `extensions` | tif,tiff,png,… | Image file extensions to pick up (case-insensitive) |
| `chunk_size` | `0` | Image sets per CellProfiler job; `0` = one job (always safe) |
| `group_regex` | — | Defines which files form one image set (see below) |
| `strict_image_count` | `false` | Fail instead of warn if CellProfiler's image-set count differs from the regex prediction |
| `save_masks` | `true` | Add mask saving |
| `mask_objects` | all | e.g. `Nuclei,Cells` |
| `mask_format` | `tiff` | `tiff` / `png` (16-bit) or `npy` (raw labels) |
| `allow_unpatched` | `false` | If patching fails, run the original pipeline instead of stopping |
| `container` | `cellprofiler/cellprofiler:4.2.8` | Use the version your `.cppipe` was saved with |
| `plugins_dir` | — | Folder of CellProfiler plugins |
| `cellprofiler_args` | `''` | Extra CLI flags passed to `cellprofiler` |
| `gzip_features` | `false` | Write `.csv.gz` |
| `publish_mode` | `copy` | `copy` / `symlink` / `link` |
| `max_cpus` / `max_memory` / `max_time` | 16 / 64.GB / 48.h | Hard caps on resource requests. **Set these to your machine or node.** |

Each CellProfiler job requests 1 CPU and 8 GB of memory. Jobs killed for running out of memory or time are retried up to 3 times, with more memory and time on each attempt. Real pipeline errors are not retried.

## Parallelising: `chunk_size` + `group_regex`

CellProfiler builds image sets with NamesAndTypes, for example matching `DNA` and `Actin` images by `Well` and `Site`. If a chunk receives only some of a site's channel files, those image sets break.

The fix is `group_regex`, which keeps all files of one image set in the same chunk. It is applied to each file's path relative to `input_dir`, and its **capture groups** form the image-set key:

| File names | `group_regex` |
|---|---|
| single channel, one file = one set | `'^(.+)$'` |
| `A01_s1_w1.tif`, `A01_s1_w2.tif` (MetaXpress) | `'^(.+?_s\d+)_w\d'` |
| `r01c01f01p01-ch1sk1fk1fl1.tiff` (Opera/Operetta) | `'(r\d+c\d+f\d+p\d+)-ch'` |
| `plate1/B03/site2_DAPI.tif` | `'^(.+/site\d+)_'` |

Each chunk compares CellProfiler's actual image-set count with the regex prediction. A mismatch is logged as a warning (or fails the run with `--strict_image_count true`), which means the regex doesn't match how NamesAndTypes groups your files.

**Keep `chunk_size 0` (no splitting) if your pipeline needs all images in one run**, for example:
- illumination correction with `CorrectIlluminationCalculate` set to "All: across cycles",
- object tracking (`TrackObjects`),
- the `Groups` module,
- `LoadData` with a CSV.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Permission denied: bin/patch_cppipe.py` | Run `chmod +x bin/*.py` |
| `Process requirement exceeds available memory` | Set `--max_memory` / `--max_cpus` to what your machine has |
| `CellProfiler reported errors while loading the pipeline` | Plugin missing (`--plugins_dir`) or the `.cppipe` is newer than the container (`--container`). The `DateRevision: 428` header line means 4.2.8. |
| `trying to overwrite ... in headless mode` | Two image sets map to the same output file name. Your own `SaveImages` writes to a flat folder while input files share names across folders. Enable "Create subfolders" in that module or rename the inputs. |
| `Per-image table is empty` | The Images/NamesAndTypes filters in your pipeline exclude all files. Check the filters against your file names and `--extensions`. |
| Image-set count warning | `group_regex` doesn't match how NamesAndTypes groups your files (see above) |
| Docker: `cellprofiler: unrecognized arguments ... bash` | Use the provided `docker` profile, which clears the image's ENTRYPOINT |
| Very slow in containers | CellProfiler sees all host cores. The pipeline pins thread counts to `task.cpus`; don't override those settings. |

## Limitations

- Masks are named after the first input image in NamesAndTypes. Multi-series files (one `.nd2`/`.czi` holding many fields) map several image sets to one file name; the run then **fails rather than overwriting masks**. Save masks with metadata-based names in your own pipeline instead.
- The whole input folder is linked into each task. This is fine on local disks and shared HPC filesystems. On cloud object storage it is copied once per chunk.
- Tested against CellProfiler 4.2.8. CellProfiler 5 changes some module internals; check `patch_report.json` if you switch.
