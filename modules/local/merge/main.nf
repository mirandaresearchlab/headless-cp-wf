/*
 * MERGE: runs once per plate, after all batches of that plate finish.
 *
 * In:   (plate, the plate manifest, all batch folders of the plate), contract.json, the scripts.
 * Does: joins the Image, Cells, Cytoplasm and Nuclei rows into one row per cell. Sorts the rows
 *       in plate image order, then by cell number. Checks columns and row counts across batches.
 * Out:  <plate>.csv.gz for CONCAT. It stays in work/. The report, published to logs/<plate>/.
 */
process MERGE {
    tag "${plate}"
    publishDir path: { "${destination}/logs/${plate}" }, mode: 'copy', pattern: 'result/logs/*', saveAs: { name -> name.tokenize('/').last() }

    input:
    val destination
    tuple val(plate), path(manifest), path(batches, stageAs: 'batches/*')
    path contract
    path code, stageAs: 'code/*'

    output:
    path "result/${plate}.csv.gz", emit: table
    path 'result/logs/*', emit: logs

    script:
    """
    python code/merge_features.py plate --plate '${plate}' --manifest '${manifest}' --batches batches \\
        --contract '${contract}' --out 'result/${plate}.csv.gz' --report result/logs/merge.json
    """
}
