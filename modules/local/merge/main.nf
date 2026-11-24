/*
 * MERGE: runs once per plate, after all batches of that plate finish.
 *
 * In:   (plate, the plate manifest, all batch folders of the plate), contract.json, the scripts.
 * Does: joins the Image, Cells, Cytoplasm and Nuclei rows into one row per cell. Sorts the rows
 *       in plate image order, then by cell number. Checks columns and row counts across batches.
 *       Converts the table to Parquet with fixed column types, then reads it back and checks it.
 * Out:  <plate>.parquet, copied to cp_features/. The report, published to logs/<plate>/.
 *       The copy (not a move) keeps the file in work/, so -resume does not run MERGE again.
 */
process MERGE {
    tag "${plate}"
    publishDir path: { "${destination}/cp_features" }, mode: 'copy', pattern: 'result/*.parquet', saveAs: { name -> name.tokenize('/').last() }
    publishDir path: { "${destination}/logs/${plate}" }, mode: 'copy', pattern: 'result/logs/*', saveAs: { name -> name.tokenize('/').last() }

    input:
    val destination
    tuple val(plate), path(manifest), path(batches, stageAs: 'batches/*')
    path contract
    path code, stageAs: 'code/*'

    output:
    path "result/${plate}.parquet", emit: table
    path 'result/logs/*', emit: logs

    script:
    """
    python code/merge_features.py plate --plate '${plate}' --manifest '${manifest}' --batches batches \\
        --contract '${contract}' --out 'result/${plate}.parquet' --report result/logs/merge.json
    """

    stub:

    // -stub: a text file, not Parquet. One line per batch that reached this MERGE task.
    """
    mkdir -p result/logs
    cat batches/*/stub.txt > 'result/${plate}.parquet'
    touch result/logs/merge.json
    """
}
