#!/usr/bin/env nextflow
nextflow.enable.dsl = 2

/*
 * Headless CellProfiler workflow.
 *
 * Data path:
 *   1. PREPARE reads every TIFF name once. It groups the files into image sets and plans the batches.
 *   2. ILLUMINATION runs once per plate. It reads all image sets of that plate and writes one
 *      correction function (.npy) per channel.
 *   3. ANALYSIS runs once per batch. It corrects, segments and measures its image sets, then saves
 *      label masks and feature tables.
 *   4. MERGE runs once per plate. It joins the batch tables into one row per cell.
 *   5. CONCAT runs once. It appends all plate tables into one CSV.
 *
 * Published layout in <outdir>/projects/<project>/ (default outdir: the launch folder):
 *   illum/<plate>/            correction functions from step 2
 *   masks/<plate>/            label masks from step 3
 *   cp_features/all_plates.csv.gz  per-cell table of all plates from step 5
 *   logs/                     adapted pipelines, manifests, task logs and QC reports
 *   report/                   Nextflow report.html, timeline.html, trace.txt (with --project)
 *
 * Batch and plate tables stay in work/. Nextflow needs them there to resume a failed run.
 * Both supplied profiles preserve work files after success and failure (cleanup = false).
 *
 * Terms:
 *   plate      one folder of TIFFs: images/<plate>/
 *   image set  all channel files of one acquisition position (well, site, X/Y)
 *   batch      a fixed group of complete image sets from one plate
 *   manifest   a CSV that lists the files of each image set (CellProfiler LoadData format)
 *   contract   contract.json: facts that PREPARE read from the pipelines (channels, objects,
 *              illumination functions, cell compartments)
 */

/*
 * PREPARE: runs once for the whole run.
 * In:   every TIFF path, the two .cppipe files, the helper scripts.
 * Does: extracts metadata from each filename with the pipeline's regex. Checks the channels and
 *       the TIFF layout. Groups files into image sets. Cuts each plate into batches. Writes
 *       working copies of the pipelines that read manifests instead of folders and that save masks.
 * Out:  the folder 'prepared' with plan.json, manifests/<plate>/*.csv and pipelines/.
 *       It is published to logs/run_inputs/.
 */
process PREPARE {
    publishDir path: { "${destination}/logs" }, mode: 'copy', saveAs: { 'run_inputs' }

    input:
    val destination
    path images, stageAs: 'tracked??????/*'
    path configs, stageAs: 'config/*'
    path code, stageAs: 'code/*'
    path plugins, stageAs: 'plugins/*'

    output:
    path 'prepared'

    script:
    """
    python code/prepare.py --configs config --batch-size ${params.batch_size}
    """
}

/*
 * ILLUMINATION: runs once per plate. Plates run in parallel.
 * In:   the plate's full manifest and all its TIFFs.
 * Does: runs 1_illumination.cppipe. It accumulates every image set of the plate, then saves
 *       one correction function per channel on the last cycle. Checks the shape and values.
 * Out:  (plate, folder with Illum<Channel>.npy and provenance.json with SHA-256 checksums).
 *       Published to illum/<plate>/.
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

/*
 * ANALYSIS: runs once per batch. Batches of all plates run in parallel within the CPU budget.
 * In:   (plate, batch, batch manifest, the batch's TIFFs, the folder with this plate's .npy files).
 * Does: checks the .npy checksums against the plate's provenance.json. Adds the .npy files to the
 *       manifest. Runs the analysis pipeline: apply illumination, segment, measure, save masks,
 *       export CSVs. Then moves shifted CellProfiler values back to their objects and validates
 *       every table and mask against the manifest.
 * Out:  (plate, batch folder with features/*.csv) for MERGE. This folder stays in work/.
 *       Label masks, published to masks/<plate>/.
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

/*
 * MERGE: runs once per plate, after all batches of that plate finish.
 * In:   (plate, the plate's full manifest, all batch folders of that plate).
 * Does: joins Image, Cells, Cytoplasm and Nuclei rows into one row per cell. Sorts the rows in
 *       plate image order, then by cell number. Checks columns and row counts across batches.
 * Out:  <plate>.csv.gz for CONCAT. It stays in work/ and is not published.
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

/*
 * CONCAT: runs once, after every plate is merged.
 * In:   all <plate>.csv.gz files.
 * Does: checks that every plate table has the same columns in the same order. Joins the plates
 *       in name order without decompressing the rows.
 * Out:  all_plates.csv.gz, moved (not copied) to cp_features/. It is the only published feature table.
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

/*
 * Collects the batch folders of each plate into one item for MERGE.
 * results: one (plate, batch folder) item per finished ANALYSIS task.
 * plan:    the batch plan from PREPARE. It gives the number of batches per plate.
 * groupKey tells groupTuple how many batches to expect. A plate is released as soon as its last
 * batch arrives, so one plate never waits for another.
 * Returns: one (plate, [batch folders sorted by name]) item per plate. The sort keeps resume stable.
 */
def plateBatches(results, plan) {
    def counts = plan.flatMap { plates -> plates.collect { p -> tuple(p.plate, p.batches.size()) } }
    results
        .combine(counts, by: 0)
        .map { plate, dir, n -> tuple(groupKey(plate, n), dir) }
        .groupTuple()
        .map { key, dirs -> tuple(key.getGroupTarget(), dirs.sort { dir -> dir.name }) }
}

/*
 * Choose this run's output folder: <outdir>/projects/<name>/.
 * <name> is --project if that folder is new, or if it already belongs to this session (a resume).
 * If --project names a folder of another run, warn and use the session ID instead.
 * Without --project, the session ID is the name.
 * run.json in the folder records the owning session.
 */
def outputFolder(warn) {
    def root = file("${params.outdir}/projects").toAbsolutePath().normalize()
    def session = workflow.sessionId.toString()
    if (params.project) {
        def folder = root.resolve(params.project.toString())
        def marker = folder.resolve('run.json')
        if (!folder.exists() || (marker.exists() && new groovy.json.JsonSlurper().parse(marker.toFile()).session_id == session)) {
            return folder
        }
        if (warn) {
            log.warn("Project '${params.project}' already exists in ${root} and belongs to another run. This run uses the session ID instead: ${root.resolve(session)}")
        }
    }
    return root.resolve(session)
}

// Resolve links in the existing ancestor, then append any missing path components.
def realPath(path) {
    if (path.exists()) {
        return path.toRealPath()
    }
    return realPath(path.parent).resolve(path.name)
}

workflow {
    // After success or failure, save the run status and a copy of .nextflow.log in logs/.
    workflow.onComplete = {
        def completedOutput = outputFolder(false)
        def marker = completedOutput.resolve('run.json')
        if (marker.exists() && new groovy.json.JsonSlurper().parse(marker.toFile()).session_id == workflow.sessionId.toString()) {
            def dir = completedOutput.resolve('logs')
            dir.mkdirs()
            def stamp = new Date().format('yyyyMMdd-HHmmss-SSS')
            dir.resolve("status-${stamp}.json").text = groovy.json.JsonOutput.toJson(
                [success: workflow.success, exit_status: workflow.exitStatus, duration: workflow.duration.toString(), session_id: workflow.sessionId.toString(), error: workflow.errorMessage, command: workflow.commandLine]
            )
            def logFile = file("${launchDir}/.nextflow.log")
            if (logFile.exists()) {
                java.nio.file.Files.copy(logFile, dir.resolve("nextflow-${stamp}.log"))
            }
        }
    }


    // Check the parameters before any task starts.
    if (!params.images || !params.configs) {
        error('Supply two folders: --images images/ --configs cp-configs/')
    }
    if (!(params.batch_size.toString() ==~ /[1-9][0-9]*/)) {
        error('--batch_size must be a positive integer')
    }
    if (!(params.total_cpus.toString() ==~ /[1-9][0-9]*/)) {
        error('--total_cpus must be a positive integer')
    }
    if ((params.task_memory as MemoryUnit) > (params.total_memory as MemoryUnit)) {
        error('--task_memory cannot exceed the shared --total_memory budget')
    }
    if ((params.task_memory as MemoryUnit).toBytes() <= 0) {
        error('--task_memory must be positive')
    }
    def imageRoot = file(params.images).toRealPath()
    def configRoot = file(params.configs).toRealPath()
    if (!imageRoot.isDirectory() || !configRoot.isDirectory()) {
        error('Both inputs must be folders')
    }
    def configs = configRoot.listFiles().findAll { config -> config.name.endsWith('.cppipe') }.sort { config -> config.name }
    if (configs*.name != ['1_illumination.cppipe', '2_analysis.cppipe']) {
        error("--configs requires exactly 1_illumination.cppipe and 2_analysis.cppipe; found ${configs*.name}")
    }

    // Output folder: <outdir>/projects/<project>/. A run never writes into another run's folder.
    if (params.project && !(params.project.toString() ==~ /[A-Za-z0-9][A-Za-z0-9_.-]*/)) {
        error('--project may contain letters, digits, dots, underscores and hyphens')
    }
    if (!params.outdir) {
        error('--outdir must name a folder')
    }
    def output = outputFolder(true)

    // Resolve symlinks in the part of each path that exists, so a linked image folder is still detected.
    if (realPath(output).startsWith(imageRoot) || realPath(workflow.workDir.toAbsolutePath().normalize()).startsWith(imageRoot)) {
        error('Output and work directories must be outside the image input folder')
    }
    if (!output.exists()) {
        output.mkdirs()
        output.resolve('run.json').text = groovy.json.JsonOutput.prettyPrint(
            groovy.json.JsonOutput.toJson(
                [session_id: workflow.sessionId.toString(), project: output.name, images: imageRoot.toString(), configs: configRoot.toString(), nextflow: nextflow.version.toString(), command: workflow.commandLine]
            )
        )
    }
    output.resolve('logs').mkdirs()
    log.info("Outputs: ${output}\nResume: nextflow run . --images '${imageRoot}' --configs '${configRoot}' --outdir '${output.parent.parent}' --project ${output.name} -resume ${workflow.sessionId}")
    def code = files("${projectDir}/bin/*.py")
    def plugins = files("${projectDir}/plugins/*.py")

    // Find every TIFF once. The sorted list goes to PREPARE as one item.
    // Nextflow tracks each file, so a changed image reruns the affected tasks on resume.
    images = channel.fromPath("${imageRoot}/**", type: 'file', hidden: false)
        .filter { image -> image.name.toLowerCase().endsWith('.tif') || image.name.toLowerCase().endsWith('.tiff') }
        .map { path ->
            if (imageRoot.relativize(path).nameCount != 2) {
                error("Expected images/<plate>/<filename>.tiff: ${path}")
            }
            path
        }
        .toSortedList()
        .map { paths ->
            if (!paths) {
                error('No TIFF inputs found')
            }
            paths
        }
    PREPARE(output.toString(), images, configs, code, plugins)
    prepared = PREPARE.out

    // Read plan.json into a list of plates. Each plate holds its manifest, its images and its batches.
    plan = prepared.map { dir ->
        new groovy.json.JsonSlurper()
            .parse(dir.resolve('plan.json').toFile())
            .collect { p ->
                [plate: p.plate, manifest: dir.resolve(p.manifest), images: p.images.collect { image -> file(image) }, batches: p.batches.collect { b -> [batch: b.batch, manifest: dir.resolve(b.manifest), images: b.images.collect { image -> file(image) }] }]
            }
    }

    // One item per plate for ILLUMINATION: (plate, full manifest, all images).
    plateJobs = plan.flatMap { plates -> plates.collect { p -> tuple(p.plate, p.manifest, p.images) } }

    // One item per batch for ANALYSIS: (plate, batch, batch manifest, batch images).
    batchJobs = plan.flatMap { plates -> plates.collectMany { p -> p.batches.collect { b -> tuple(p.plate, b.batch, b.manifest, b.images) } } }
    contract = prepared.map { dir -> dir.resolve('pipelines/contract.json') }
    ILLUMINATION(output.toString(), plateJobs, prepared.map { dir -> dir.resolve('pipelines/illumination.cppipe') }, contract, code, plugins)

    // combine(by: 0) pairs each batch with the .npy folder of the same plate.
    // A plate's batches start as soon as that plate's illumination finishes.
    ANALYSIS(
        output.toString(),
        batchJobs.combine(ILLUMINATION.out.functions, by: 0),
        prepared.map { dir -> dir.resolve('pipelines/analysis.cppipe') },
        contract,
        code,
        plugins,
    )

    // MERGE gets (plate, full manifest) joined with (plate, all batch folders).
    MERGE(
        output.toString(),
        plateJobs.map { plate, manifest, _paths -> tuple(plate, manifest) }.join(plateBatches(ANALYSIS.out.results, plan)),
        contract,
        code,
    )

    // toSortedList waits for every plate table. This is the only step that waits for all plates.
    CONCAT(output.toString(), MERGE.out.table.toSortedList { a, b -> a.name <=> b.name }, code)
}
