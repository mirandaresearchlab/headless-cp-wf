/*
 * ANALYSIS: runs once per batch. Batches of all plates run in parallel within the CPU budget.
 *
 * In:   (plate, batch, batch manifest, the batch's images, the folder with this plate's .npy
 *       files), the working copy of 2_analysis.cppipe, contract.json, the scripts and plugins.
 * Does: checks the .npy checksums against the plate's provenance.json. Runs CellProfiler:
 *       apply illumination, segment, measure, save masks, export CSVs. Then moves shifted
 *       CellProfiler 4.2.8.1 values back to their objects and checks every table and mask.
 * Out:  (plate, batch folder with features/*.csv.gz) for MERGE. This folder stays in work/.
 *       Label masks, published to masks/<plate>/. Task logs, published to logs/<plate>/.
 */
process ANALYSIS {
    tag "${plate}/${batch}"
    publishDir path: { "${destination}/masks/${plate}" }, mode: 'copy', pattern: 'result/masks/*.tiff', saveAs: { name -> name.tokenize('/').last() }
    publishDir path: { "${destination}/logs/${plate}" }, mode: 'copy', pattern: 'result/logs/*', saveAs: { name -> name.tokenize('/').last() }

    input:
    val destination
    tuple val(plate), val(batch), path(manifest), path(images, stageAs: 'tracked??????/*'), path(illumination)
    path pipeline
    path contract
    path code, stageAs: 'code/*'
    path plugins, stageAs: 'plugins/*'

    output:
    tuple val(plate), path("result/analysis/${batch}"), emit: results
    path 'result/masks/*.tiff', emit: masks
    path 'result/logs/*', emit: logs

    script:
    """
    python code/run_task.py analysis --plate '${plate}' --batch '${batch}' \\
        --manifest '${manifest}' --pipeline '${pipeline}' --contract '${contract}' \\
        --illumination '${illumination}'
    """
}
