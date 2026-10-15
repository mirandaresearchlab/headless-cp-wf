# Prepare your image folder

This guide tells you how to arrange your image files, for images with one channel and for images with
several channels. It also tells you how the workflow uses the channels, and where you define them.

Read [Run on your data](../usage.md) for the other parts of a run.

## What the workflow does with your folder

1. It searches `--input_dir` and all its sub-folders for files with an image extension (`--extensions`).
   It skips hidden files.
2. It applies `--group_regex` to the path of each file, **relative to `--input_dir`**, for example
   `plate1/A01_s1_w1.tif`. The parts in round brackets make the name of an **image set**. Files with the
   same name belong to the same image set.
3. It checks the image sets. Every file must match the pattern. Every image set must have the same number
   of files. If a check fails, the run stops before CellProfiler starts, and the message shows examples.
4. It puts whole image sets into chunks. It never splits an image set between two jobs.

A **channel** is one color of light, for example `DNA`. An **image set** is all channel files of one site.

!!! important "The workflow does not name your channels"
    The workflow only counts the files of each image set and keeps them together. It does not know that
    `w1` is `DNA` and `w2` is `Actin`. **Your CellProfiler pipeline gives the channels their names**, in the
    NamesAndTypes module. See [Define the channels in your pipeline](#define-the-channels-in-your-pipeline).

## The rules for every folder

| Rule | Why |
| --- | --- |
| Use one file name pattern for the whole experiment. | One `--group_regex` must fit every file. |
| Put the plate, well and site in the file name or in the folder names. | The Metadata module reads them from there. Profiling needs them. |
| Give every site the same files, one for each channel. | An image set with a missing channel stops the run. |
| Keep thumbnails, overlays, old results and other images out of the folder. | They do not match `--group_regex` and stop the run. |
| Put `--outdir` outside the image folder. | The workflow stops if it is inside. |
| Count z-planes and time points as files. | A site with 2 channels and 3 z-planes has 6 files. All 6 must be in the same image set. |

## One channel

Each file is one image set. Use this pattern:

```bash
--group_regex '^(.+)$'
```

Any folder layout works, because the whole path is the name of the image set. For example:

```text
images/
├── plate1/
│   ├── A01_s1.tif
│   ├── A01_s2.tif
│   └── ...
└── plate2/
    └── ...
```

The test data of the workflow has this form (`tests/images/plate1/site0_DNA.tif`).

The pipeline needs no channel rules. In NamesAndTypes, assign **all images** to one name, for example
`DNA`. The test pipeline `tests/test.cppipe` does this.

## Several channels

The microscope saves one file for each channel. All files of a site must have the same image-set name. The
channel part of the file name must **not** be in a bracket of `--group_regex`, because it differs between the
files of one site.

Choose the layout that your microscope made. The patterns here are examples: change them to fit your
file names.

=== "All files in one folder"

    ```text
    images/
    ├── A01_s1_w1.tif    A01_s1_w2.tif
    ├── A01_s2_w1.tif    A01_s2_w2.tif
    └── ...
    ```

    ```bash
    --group_regex '^(.+?_s\d+)_w\d'
    ```

    Image sets: `A01_s1` and `A01_s2`, with 2 files each.

=== "One folder for each plate"

    ```text
    images/
    ├── plate1/
    │   ├── A01_s1_w1.tif    A01_s1_w2.tif
    │   └── ...
    └── plate2/
        └── ...
    ```

    ```bash
    --group_regex '^(.+?_s\d+)_w\d'
    ```

    The folder name is part of the image-set name (`plate1/A01_s1`). Thus the same well in two plates gives
    two image sets.

=== "One folder for each well"

    ```text
    images/
    └── plate1/
        └── A01/
            ├── s1_w1.tif    s1_w2.tif
            └── s2_w1.tif    s2_w2.tif
    ```

    ```bash
    --group_regex '^(.+/s\d+)_w\d'
    ```

=== "One folder for each channel"

    ```text
    images/
    └── plate1/
        ├── DAPI/
        │   ├── A01_s1.tif
        │   └── A01_s2.tif
        └── Actin/
            ├── A01_s1.tif
            └── A01_s2.tif
    ```

    ```bash
    --group_regex '^([^/]+)/(?:DAPI|Actin)/(.+)\.tif$'
    ```

    The pattern has two brackets: the plate folder and the file name. The channel folder has no bracket
    (`(?:...)` does not make a part of the name). Image sets: `plate1|A01_s1` and `plate1|A01_s2`.

=== "Opera or Operetta"

    ```text
    images/
    └── r01c01f01p01-ch1sk1fk1fl1.tiff    r01c01f01p01-ch2sk1fk1fl1.tiff
    ```

    ```bash
    --group_regex '(r\d+c\d+f\d+p\d+)-ch'
    ```

I checked these patterns against example file lists. They give the image sets that the text shows.

### Files that hold all channels

Some formats keep all channels of a site in one file, for example `.nd2`, `.czi` or `.lif`. The workflow
finds these files, and each file is one image set: use `--group_regex '^(.+)$'`. We did not test these
formats with the workflow. Test them with a small set of files first.

### Check the folder before a large run

Run the workflow with `-stub-run` on your folder. The stub jobs only make small files and do not start
CellProfiler, so the run is fast. The checks of the image sets run first:

```bash
nextflow run . -profile local -stub-run \
    --pipeline /path/to/analysis.cppipe \
    --input_dir /path/to/images \
    --outdir /path/to/stub-results \
    --group_regex '^(.+?_s\d+)_w\d' \
    --max_cpus 2 --max_memory 3.GB
```

Look at these lines in the log. This example has 2 channels and 6 sites:

```text
[cp-headless] image sets have 2 file(s) each (most common size)
[cp-headless] 6 image set(s), 12 file(s) -> 1 chunk(s)
```

- `N file(s) each` must be your number of channels (times z-planes and time points, if you have them).
- `image set(s)` must be your number of sites.

If the numbers are wrong, or the run stops with a message about `--group_regex`, change the pattern. See
[Troubleshooting](troubleshooting.md#errors-before-cellprofiler-starts).

!!! warning "What this check does not find"
    The check only looks at how the file names group into image sets. It does not open the images, and it
    does not look at the names for other problems. Check these things yourself:

    - **Bit depth.** All channels and plates must have the same bit depth (for example 16-bit). Mixed bit
      depths give intensity features that you cannot compare.
    - **Spaces and non-ASCII characters** in file and folder names. Some tools fail on them. Rename the
      files, or work on a copy.
    - **Well names.** Write wells in the same form everywhere: `A01`, not `A1`. A different form splits one
      well into two in the result tables.
    - **Metadata.** The check does not read plate, well and site. Use `--required_metadata` to stop the run
      if a value is missing. See [Run on your data](../usage.md#metadata-for-profiling).

## Define the channels in your pipeline

You do this in the CellProfiler program, with a sample of your images, before you use the workflow. **Skip
this section if your pipeline already names its channels**, or if your images have one channel.

1. **Metadata** module. Turn on "Extract metadata". Read the plate, well, site and channel from the file
   name with a regular expression. For the file names `A01_s1_w1.tif`:

   ```text
   (?P<Well>[A-P][0-9]{2})_s(?P<Site>\d+)_w(?P<Channel>\d)
   ```

   If the plate is in the folder name, add a second extraction from the folder with
   `(?P<Plate>plate\d+)`.

2. **NamesAndTypes** module. Choose "Images matching rules". Make one rule for each channel, and give each
   one a name:

   | Rule | Image name |
   | --- | --- |
   | Metadata does `Channel` equal `1` | `DNA` |
   | Metadata does `Channel` equal `2` | `Actin` |

   Set the image set matching method to **Metadata**. Match `Well` and `Site` (and `Plate`) across the
   channels. Matching by metadata is safer than matching by order, because a missing file cannot shift the
   other files.

3. Use the names `DNA` and `Actin` in the modules after it, for example in IdentifyPrimaryObjects.
4. Save the pipeline as a `.cppipe` file in CellProfiler 4.2.8.

The names that you choose in NamesAndTypes appear in the result tables. The workflow keeps them as they are.

### How the two settings fit together

| Setting | Where | What it controls |
| --- | --- | --- |
| `--group_regex` | The workflow | Which files are one site, so that a chunk holds whole image sets |
| NamesAndTypes rules and matching | Your pipeline | Which file is which channel, and how CellProfiler builds an image set |

The two must agree. If `--group_regex` puts two sites in one set, but NamesAndTypes expects one site, the
workflow stops with `CellProfiler processed N image sets but the workflow predicted M`.

For all pipeline requirements, see [CellProfiler pipelines](../reference/pipelines.md). For the checks, see
[Data checks and design](../explanation/design.md).
