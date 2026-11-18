/*
 * CONCAT: runs once, after every plate is merged.
 *
 * In:   all <plate>.csv.gz files, the scripts.
 * Does: checks that every plate table has the same columns in the same order. Joins the plates
 *       in name order without decompressing the rows.
 * Out:  all_plates.csv.gz, moved (not copied) to cp_features/. It is the only published table.
 *       Because the file is moved, CONCAT runs again on -resume.
 */
process CONCAT {
    publishDir path: { "${destination}/cp_features" }, mode: 'move', pattern: 'result/*.csv.gz', saveAs: { name -> name.tokenize('/').last() }
    publishDir path: { "${destination}/logs" }, mode: 'copy', pattern: 'result/*.json', saveAs: { name -> name.tokenize('/').last() }

    input:
    val destination
    path tables, stageAs: 'plates/*'
    path code, stageAs: 'code/*'

    output:
    path 'result/all_plates.csv.gz', emit: table
    path 'result/all_plates.merge.json', emit: logs

    script:
    """
    mkdir -p result
    python code/merge_features.py all plates/*.csv.gz --out result/all_plates.csv.gz --report result/all_plates.merge.json
    """
}
