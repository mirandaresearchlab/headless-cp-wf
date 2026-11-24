/*
 * ANALYSIS: runs once per batch. Batches of all plates run in parallel within the CPU budget.
 *
 * In:   (plate, batch, batch manifest, the batch's images, the folder with this plate's .npy
 *       files, the SEGMENT folder of the batch or [] without RunCellpose), the working copy of
 *       2_analysis.cppipe, contract.json, the scripts and plugins.
 * Does: checks the .npy checksums against the plate's provenance.json. Runs CellProfiler:
 *       apply illumination, segment (or load the SEGMENT masks in place of RunCellpose), measure,
 *       save masks, export CSVs. Then moves shifted CellProfiler 4.2.8.1 values back to their
 *       objects and checks every table and mask. With RunCellpose, it also checks that the saved
 *       masks of the Cellpose objects equal the SEGMENT masks.
 * Out:  (plate, batch folder with features/*.csv.gz) for MERGE. This folder stays in work/.
 *       Label masks, published to masks/<plate>/. Task logs, published to logs/<plate>/.
 */
process ANALYSIS {
    tag "${plate}/${batch}"
    publishDir path: { "${destination}/masks/${plate}" }, mode: 'copy', pattern: 'result/masks/*.tiff', saveAs: { name -> name.tokenize('/').last() }
    publishDir path: { "${destination}/logs/${plate}" }, mode: 'copy', pattern: 'result/logs/*', saveAs: { name -> name.tokenize('/').last() }

    input:
    val destination
    tuple val(plate), val(batch), path(manifest), path(images, stageAs: 'tracked??????/*'), path(illumination), path(segmentation, stageAs: 'segmentation')
    path pipeline
    path contract
    path code, stageAs: 'code/*'
    path plugins, stageAs: 'plugins/*'

    output:
    tuple val(plate), path("result/analysis/${batch}"), emit: results
    path 'result/masks/*.tiff', emit: masks
    path 'result/logs/*', emit: logs

    script:
    def masks = segmentation ? "--segmentation '${segmentation}'" : ''
    """
    python code/run_task.py analysis --plate '${plate}' --batch '${batch}' \\
        --manifest '${manifest}' --pipeline '${pipeline}' --contract '${contract}' \\
        --illumination '${illumination}' ${masks}
    """

    stub:

    // -stub: stub.txt records the plate, batch, manifest, illumination folder and SEGMENT folder
    // that the task got. MERGE collects these lines, so the tests can check every join.
    def segmented = segmentation ? "\$(cat '${segmentation}/stub.txt')" : 'none'
    """
    mkdir -p 'result/analysis/${batch}' result/masks result/logs
    echo "plate=${plate} batch=${batch} manifest=\$(basename '${manifest}') illumination=\$(cat '${illumination}/plate.txt') segmentation=[${segmented}]" > 'result/analysis/${batch}/stub.txt'
    touch 'result/masks/${plate}_${batch}_stub.tiff' result/logs/analysis.json
    """
}
