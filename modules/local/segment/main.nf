/*
 * SEGMENT: runs once per group of --segmentation_batches batches of one plate, only if
 * 2_analysis.cppipe has RunCellpose modules. Groups of all plates run in parallel.
 *
 * In:   (plate, group name, the batch manifests of the group, their images, the folder with this
 *       plate's .npy files), the SEGMENT pipeline from PREPARE, contract.json, the scripts and plugins.
 * Does: runs --segmentation_workers CellProfiler processes at the same time, each on a part of the
 *       group. They run RunCellpose (Cellpose-SAM) and the modules that make its input image, on
 *       the GPU (--segmentation gpu; all workers share it) or on the CPU. Then checks every mask
 *       against its image set and raw files, and sorts the masks into one folder per batch.
 * Out:  (plate, one folder per batch with masks/, mask_manifest.csv and validation.json) for
 *       ANALYSIS. These stay in work/: ANALYSIS saves the same masks again and publishes them.
 *       Task logs (with GPU use per second), published to logs/<plate>/.
 *       With --segmentation_only, ANALYSIS does not run, so SEGMENT publishes each batch folder
 *       to masks/<plate>/<batch>/ (masks/*.tiff, mask_manifest.csv, validation.json).
 */
process SEGMENT {
    tag "${plate}/${group}"
    label 'segmentation'
    publishDir path: { "${destination}/logs/${plate}" }, mode: 'copy', pattern: 'result/logs/*', saveAs: { name -> name.tokenize('/').last() }
    // Only with --segmentation_only: each batch folder whole (Nextflow does not publish single files
    // inside a folder that is itself an output).
    publishDir path: { "${destination}/masks/${plate}" }, mode: 'copy', pattern: 'result/segmentation/*', saveAs: { name -> name.tokenize('/').last() }, enabled: params.segmentation_only.toString() == 'true'

    input:
    val destination
    tuple val(plate), val(group), path(manifests, stageAs: 'manifests/*'), path(images, stageAs: 'tracked??????/*'), path(illumination)
    path pipeline
    path contract
    path code, stageAs: 'code/*'
    path plugins, stageAs: 'plugins/*'

    output:
    tuple val(plate), path('result/segmentation/*'), emit: batches
    path 'result/logs/*', emit: logs

    script:
    """
    python code/run_task.py segmentation --plate '${plate}' --batch '${group}' \\
        --manifest manifests/*.csv --pipeline '${pipeline}' --contract '${contract}' \\
        --illumination '${illumination}' --device ${params.segmentation} \\
        --workers ${params.segmentation_workers} --cpus ${task.cpus}
    """

    stub:

    // -stub: one folder per batch of the group, named like the batch (as run_task.py does).
    // stub.txt records the plate, the group and the illumination folder that the task got.
    """
    mkdir -p result/logs
    for manifest in manifests/*.csv; do
        batch=\$(basename "\$manifest" .csv)
        mkdir -p "result/segmentation/\$batch/masks"
        touch "result/segmentation/\$batch/masks/${plate}_\${batch}_segment_stub.tiff"
        echo "Plate,Batch,MaskPath" > "result/segmentation/\$batch/mask_manifest.csv"
        echo "plate=${plate} group=${group} batch=\$batch illumination=\$(cat '${illumination}/plate.txt')" > "result/segmentation/\$batch/stub.txt"
    done
    touch result/logs/segmentation.json
    """
}
