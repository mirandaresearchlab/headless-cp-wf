# Glossary

| Term | Meaning |
| --- | --- |
| Plate | A plastic plate with many small wells (for example 96 or 384). Each well holds cells. |
| Well | One position on a plate, for example `A01`. |
| Site | One field of view in a well. The microscope often takes images of several sites per well. |
| Channel | One color of light, which shows one stain. For example, `DNA` shows the nucleus. |
| Image set | All channel images of one site. CellProfiler analyzes one image set at a time. |
| Object | Something that CellProfiler finds in the images, for example a nucleus or a cell. |
| Feature | One measurement of an object or an image, for example the area of a nucleus. |
| Mask | An image in which the pixels of object 1 have the value 1, of object 2 the value 2, and so on. The value 0 is the background. |
| Metadata | Information about an image, for example its plate, well and site. CellProfiler can read it from file names. |
| Image-based profiling | Comparing the features of cells between treatments, for example drugs or gene changes. |
| Pipeline | A CellProfiler file (`.cppipe`) that lists the analysis steps (modules) and their settings. |
| Module | One step of a CellProfiler pipeline, for example IdentifyPrimaryObjects. |
| Headless | Without the graphical window of a program. |
| Chunk | A group of image sets that one CellProfiler job processes. |
| Job (task) | One run of one step of the workflow, for example CellProfiler on one chunk. |
| Profile | A named group of settings for Nextflow, chosen with `-profile`, for example `docker`. |
| Container | A package that holds CellProfiler and everything that it needs. The same container gives the same results on each computer. |
| Digest | A unique fingerprint of a container image (`sha256:...`). It never changes. |
| Cluster (HPC) | A group of many computers. A scheduler, for example Slurm, gives jobs to the computers. |
| Head job | The long cluster job that runs Nextflow. Nextflow then submits the other jobs. |
| Stub run | A run with `-stub-run`: the jobs make small fake files instead of running CellProfiler. It checks how the steps connect. |
