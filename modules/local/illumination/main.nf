/*
 * ILLUMINATION: runs once per plate. Plates run in parallel.
 *
 * In:   (plate, the plate manifest with all its image sets, all its images), the working copy
 *       of 1_illumination.cppipe, contract.json, the helper scripts and the plugins.
 * Does: runs CellProfiler over every image set of the plate. It saves one correction function
 *       per channel on the last cycle, then checks the shape and the values of each function.
 * Out:  (plate, folder with Illum<Channel>.npy and provenance.json with SHA-256 checksums),
 *       published to illum/<plate>/. Task logs, published to logs/<plate>/.
 */
process ILLUMINATION {
    tag "${plate}"
    publishDir path: { "${destination}/illum" }, mode: 'copy', pattern: 'result/illumination', saveAs: { plate }
    publishDir path: { "${destination}/logs/${plate}" }, mode: 'copy', pattern: 'result/logs/*', saveAs: { name -> name.tokenize('/').last() }

    input:
    val destination
    tuple val(plate), path(manifest), path(images, stageAs: 'tracked??????/*')
    path pipeline
    path contract
    path code, stageAs: 'code/*'
    path plugins, stageAs: 'plugins/*'

    output:
    tuple val(plate), path('result/illumination'), emit: functions
    path 'result/logs/*', emit: logs

    script:
    """
    python code/run_task.py illumination --plate '${plate}' \\
        --manifest '${manifest}' --pipeline '${pipeline}' --contract '${contract}'
    """
}
