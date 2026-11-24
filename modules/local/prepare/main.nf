/*
 * PREPARE: runs once for the whole run, before any CellProfiler task.
 *
 * In:   the samplesheet, every image file in it (staged, so Nextflow tracks changes),
 *       the two .cppipe files, the helper scripts and the plugins.
 * Does: checks every samplesheet row and file. Groups the files into image sets and cuts each
 *       plate into batches. Writes working copies of the pipelines that read LoadData manifests
 *       and save label masks.
 * Out:  the folder 'prepared' with samplesheet.csv, plan.json, manifests/<plate>/*.csv and
 *       pipelines/. It is published to logs/run_inputs/.
 */
process PREPARE {
    publishDir path: { "${destination}/logs" }, mode: 'copy', saveAs: { 'run_inputs' }

    input:
    val destination
    path images, stageAs: 'tracked??????/*'
    path samplesheet, stageAs: 'input/samplesheet.csv'
    path configs, stageAs: 'config/*'
    path code, stageAs: 'code/*'
    path plugins, stageAs: 'plugins/*'

    output:
    path 'prepared'

    script:
    """
    python code/prepare.py --configs config --samplesheet '${samplesheet}' --batch-size ${params.batch_size}
    """

    stub:

    // -stub: the real samplesheet checks and batch plan, without CellProfiler (see prepare.py --stub).
    """
    python code/prepare.py --configs config --samplesheet '${samplesheet}' --batch-size ${params.batch_size} --stub
    """
}
