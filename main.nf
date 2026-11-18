#!/usr/bin/env nextflow
/*
 * Headless CellProfiler: entry point.
 *
 *   nextflow run . -profile local --input samplesheet.csv --configs cp-configs --project screen01
 *
 * This file checks the parameters, chooses the output folder, and starts the workflow in
 * workflows/cellprofiler.nf. The processes are in modules/local/. The scripts are in bin/.
 *
 * Results go to <outdir>/projects/<project>/:
 *   illum/<plate>/                 correction functions (ILLUMINATION)
 *   masks/<plate>/                 label masks (ANALYSIS)
 *   cp_features/all_plates.csv.gz  per-cell table of all plates (CONCAT)
 *   logs/                          run inputs, manifests, task logs and checks
 *   report/                        Nextflow report.html, timeline.html, trace.txt (with --project)
 * Batch and plate tables stay in work/. Nextflow needs them there to resume a stopped run.
 */

include { CELLPROFILER } from './workflows/cellprofiler'

workflow {
    // After success or failure, save the run status and a copy of .nextflow.log in logs/.
    workflow.onComplete = {
        def output = outputFolder(false)
        if (ownedBy(output, workflow.sessionId.toString())) {
            def logs = output.resolve('logs')
            logs.mkdirs()
            def stamp = new Date().format('yyyyMMdd-HHmmss-SSS')
            logs.resolve("status-${stamp}.json").text = groovy.json.JsonOutput.toJson(
                [success: workflow.success, exit_status: workflow.exitStatus, duration: workflow.duration.toString(), session_id: workflow.sessionId.toString(), error: workflow.errorMessage, command: workflow.commandLine]
            )
            def logFile = file("${launchDir}/.nextflow.log")
            if (logFile.exists()) {
                java.nio.file.Files.copy(logFile, logs.resolve("nextflow-${stamp}.log"))
            }
        }
    }

    def (sheet, configRoot, configs) = checkParameters()

    // Output folder: <outdir>/projects/<project>/. A run never writes into another run's folder.
    def output = outputFolder(true)
    if (!output.resolve('run.json').exists()) {
        output.mkdirs()
        output.resolve('run.json').text = groovy.json.JsonOutput.prettyPrint(
            groovy.json.JsonOutput.toJson(
                [session_id: workflow.sessionId.toString(), project: output.name, input: sheet.toString(), configs: configRoot.toString(), nextflow: nextflow.version.toString(), command: workflow.commandLine]
            )
        )
    }
    output.resolve('logs').mkdirs()
    log.info("Outputs: ${output}\nResume: nextflow run . --input '${sheet}' --configs '${configRoot}' --outdir '${output.parent.parent}' --project ${output.name} -resume ${workflow.sessionId}")

    CELLPROFILER(output.toString(), sheet, configs, files("${projectDir}/bin/*.py"), files("${projectDir}/plugins/*.py"))
}

/*
 * Check the parameters before any task starts.
 *
 * Returns the samplesheet (real path), the configuration folder (real path), and the two
 * .cppipe files in name order.
 */
def checkParameters() {
    if (!params.input || !params.configs) {
        error('Supply --input samplesheet.csv and --configs cp-configs/')
    }
    if (!(params.batch_size.toString() ==~ /[1-9][0-9]*/)) {
        error('--batch_size must be a positive integer')
    }
    if (!(params.total_cpus.toString() ==~ /[1-9][0-9]*/)) {
        error('--total_cpus must be a positive integer')
    }
    if ((params.task_memory as MemoryUnit).toBytes() <= 0 || (params.task_memory as MemoryUnit) > (params.total_memory as MemoryUnit)) {
        error('--task_memory must be positive and cannot exceed --total_memory')
    }
    if (params.project && !(params.project.toString() ==~ /[A-Za-z0-9][A-Za-z0-9_.-]*/)) {
        error('--project may contain letters, digits, dots, underscores and hyphens')
    }
    if (!params.outdir) {
        error('--outdir must name a folder')
    }
    def sheet = file(params.input)
    if (!sheet.isFile()) {
        error("--input must be a samplesheet CSV file: ${params.input}")
    }
    def configRoot = file(params.configs)
    if (!configRoot.isDirectory()) {
        error("--configs must be a folder: ${params.configs}")
    }
    def configs = configRoot.listFiles().findAll { config -> config.name.endsWith('.cppipe') }.sort { config -> config.name }
    if (configs*.name != ['1_illumination.cppipe', '2_analysis.cppipe']) {
        error("--configs requires exactly 1_illumination.cppipe and 2_analysis.cppipe; found ${configs*.name}")
    }
    return [sheet.toRealPath(), configRoot.toRealPath(), configs]
}

/*
 * Choose this run's output folder: <outdir>/projects/<name>/.
 *
 * <name> is --project if that folder is free for this run. A folder is free if it does not exist,
 * if its run.json names this session (a resume), or if it holds only report/: Nextflow makes
 * report/ at startup, before this check. If another run owns the folder, warn and use the
 * session ID as the name. Without --project, the session ID is the name.
 */
def outputFolder(warn) {
    def root = file("${params.outdir}/projects").toAbsolutePath().normalize()
    def session = workflow.sessionId.toString()
    if (params.project) {
        def folder = root.resolve(params.project.toString())
        def onlyReports = folder.exists() && !folder.resolve('run.json').exists() && folder.toFile().list().every { name -> name == 'report' }
        if (!folder.exists() || onlyReports || ownedBy(folder, session)) {
            return folder
        }
        if (warn) {
            log.warn("Project '${params.project}' already exists in ${root} and belongs to another run. This run uses the session ID instead: ${root.resolve(session)}")
        }
    }
    return root.resolve(session)
}

// True if the run.json of the folder names this session.
def ownedBy(folder, session) {
    def marker = folder.resolve('run.json')
    return marker.exists() && new groovy.json.JsonSlurper().parse(marker.toFile()).session_id == session
}
