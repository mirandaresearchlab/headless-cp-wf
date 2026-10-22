#!/usr/bin/env nextflow

/*
 * cp-headless
 * ---------------
 * Runs CellProfiler without its window ("headless") on microscope images, plate by plate.
 * You give it three things:
 *   --illum_pipeline 1_illumination.cppipe   calculates the illumination functions (once per plate)
 *   --pipeline       2_analysis.cppipe       segments the cells and measures the features (in chunks)
 *   --input_dir      /path/to/images         one sub-folder per plate
 * Both pipelines are made in the CellProfiler program. Without --illum_pipeline, the workflow runs only
 * --pipeline (for pipelines that need no illumination functions, or with --illum_dir).
 *
 * It makes one table per object type with the cells of all plates (Image.csv, Cells.csv, Nuclei.csv,
 * Cytoplasm.csv, with a unique ImageNumber and the plate, well and site in every row), a mask for each object
 * type in each image set (16-bit labels), and a list that connects each mask to its images.
 *
 * The file has three parts:
 *   1. helper functions  - parameter checks, the plan of plates and chunks, and the run report
 *   2. processes         - the job types: PATCH_PIPELINE, ILLUM, CELLPROFILER, MERGE_FEATURES
 *   3. workflow          - finds the images, groups them into plates and chunks, and connects the jobs
 */

nextflow.enable.dsl = 2

// ------------------------------------------------------------------ helpers

// Stop the run with one clear message. All checks in this file use it.
def cpnfError(String msg) {
    error("[cp-headless] ERROR: ${msg}")
}

// Nextflow passes `--flag false` from the command line as the STRING 'false', and Groovy
// treats every non-empty string as true. Read boolean parameters only through this function.
def boolParam(String name) {
    def value = params[name]
    if (value instanceof Boolean) return value
    def text = value == null ? '' : value.toString().trim().toLowerCase()
    if (text in ['true', 'yes', '1']) return true
    if (text in ['false', 'no', '0', '']) return false
    cpnfError("--${name} must be true or false, not '${value}'")
}

// Turn --extensions 'tif,.TIFF, png' into the list [tif, tiff, png]: lower case, without dots.
def imageExtensions() {
    params.extensions.toString().tokenize(',')
        .collect { ext -> ext.trim().toLowerCase().replaceFirst(/^\./, '') }
        .findAll { ext -> ext }
}

// True if the path is inside the home folder of the user ($HOME).
def inHomeDir(path) {
    def home = System.getenv('HOME')
    if (!home || path == null) return false
    def abs = file(path.toString()).toAbsolutePath().normalize()
    return abs.startsWith(file(home).toAbsolutePath().normalize())
}

// Plate names: letters, digits, '.', '_' and '-'. They become folder and file names in the results.
def plateNamePattern() {
    ~/[A-Za-z0-9._-]+/
}

// Folders of the results that a plate folder must not replace: results/<plate>/ sits next to them.
def reservedPlateNames() {
    ['all_plates', 'cellprofiler_tables', 'profiles', 'pipeline', 'pipeline_info', 'logs']
}

// The plate of a file: the first folder of its path below input_dir, or group 1 of --plate_regex.
// null if the file has none: a file directly in input_dir, or a path that plate_regex does not match.
def plateOf(String rel, plateRegex) {
    if (plateRegex) {
        def m = plateRegex.matcher(rel)
        return m.find() ? m.group(1) : null
    }
    def parts = rel.tokenize('/')
    return parts.size() > 1 ? parts[0] : null
}

// The image set of a file: the capture groups of group_regex. Files with the same key belong to the
// same site. A file that does not match gets an "__unmatched__" key of its own. Without group_regex,
// each file is an image set of its own ("__single__").
def imageSetOf(String rel, groupPattern) {
    if (!groupPattern) return "__single__/${rel}"
    def m = groupPattern.matcher(rel)
    if (!m.find()) return "__unmatched__/${rel}"
    return m.groupCount() > 0 ? (1..m.groupCount()).collect { i -> m.group(i) ?: '' }.join('|') : m.group(0)
}

// Memory of one analysis chunk, in GB: --memory_per_cpu x --segmentation_cpus (for the log only; the
// config sets the same value for the jobs).
def chunkMemoryGB() {
    def perCpu = params.memory_per_cpu as nextflow.util.MemoryUnit
    return perCpu.toGiga() * (params.segmentation_cpus as int)
}

// The plate of a chunk: a chunk ID is always <plate>_chunk_<number>.
def plateOfChunk(String chunkId) {
    chunkId.replaceFirst(/_chunk_\d+$/, '')
}

// The path below outdir of a file that a chunk job publishes. fn is the path in the job folder,
// <chunk>/<path>. Masks (<chunk>/masks/<folders of the input>/...) go to <plate>/masks/, without the plate
// folder a second time (check_chunk.py makes the same path). Other files that the pipeline saves go to
// <plate>/cellprofiler_outputs/<chunk>/<path>.
def publishedChunkPath(String fn) {
    def chunkId = fn.tokenize('/')[0]
    def plate = plateOfChunk(chunkId)
    def rel = fn.substring(chunkId.length() + 1)
    if (!rel.startsWith('masks/')) return "${plate}/cellprofiler_outputs/${fn}"
    rel = rel.substring('masks/'.length())
    return rel.startsWith("${plate}/") ? "${plate}/masks/${rel.substring(plate.length() + 1)}" : "${plate}/masks/${rel}"
}

// The names of the modules in a .cppipe file (a text file). A .cpproj file (HDF5) gives an empty list.
def pipelineModules(path) {
    def f = file(path)
    if (!f.name.toLowerCase().endsWith('.cppipe')) return []
    return (f.text =~ /(?m)^(\w+):\[module_num/).collect { m -> m[1] }
}

// Berzelius site rules (see conf/berzelius.config). They stop the run before any job is submitted.
def validateBerzelius() {

    // Every job needs a project account, and CellProfiler must run on a CPU partition.
    def cpuPartitions = ['berzelius-cpu', 'berzelius-hopper-cpu']
    if (!params.slurm_account)
        cpnfError("-profile berzelius needs --slurm_account <project account>. Run `projinfo` on a login node to see it.")
    if (!(params.slurm_partition?.toString() in cpuPartitions))
        cpnfError("-profile berzelius needs --slurm_partition berzelius-cpu (Ampere system) or " +
            "berzelius-hopper-cpu (Hopper system), not '${params.slurm_partition}'. CellProfiler uses only CPUs: " +
            "on a GPU partition your project pays for GPUs that stay idle.")

    // $HOME on Berzelius has 20 GB and 1 million files. Work files, results and images go to /proj.
    if (inHomeDir(workflow.workDir))
        cpnfError("the work directory ${workflow.workDir} is in your home directory (20 GB, 1 million files). " +
            "Use -work-dir /proj/<project>/users/\$USER/...")
    if (inHomeDir(params.outdir))
        cpnfError("--outdir ${params.outdir} is in your home directory (20 GB, 1 million files). Use /proj/<project>/...")
    if (inHomeDir(params.container_cache))
        cpnfError("--container_cache ${params.container_cache} is in your home directory (20 GB). Use /proj/<project>/...")
    if (!params.container_cache)
        log.warn "[cp-headless] Berzelius: set --container_cache /proj/<project>/users/\$USER/containers, " +
            "otherwise every new work directory downloads the CellProfiler image again."
}

// Check one CellProfiler pipeline file: it exists, and it is a .cppipe or .cpproj file.
def validatePipelineFile(String name) {
    def p = file(params[name])
    if (!p.exists() || p.isDirectory()) cpnfError("--${name}: file not found: ${params[name]}")
    if (!(p.name.toLowerCase() ==~ /.*\.(cppipe|cpproj)$/))
        log.warn "[cp-headless] '${p.name}' does not end in .cppipe/.cpproj - trying anyway"
}

// Check all parameters before any job starts, so that a wrong setting fails in seconds, not hours.
def validateParams() {

    // The required inputs: the analysis pipeline and the image folder.
    if (!params.pipeline)  cpnfError("--pipeline is required (path to a .cppipe or .cpproj file)")
    if (!params.input_dir) cpnfError("--input_dir is required (folder containing your images, one sub-folder per plate)")
    validatePipelineFile('pipeline')

    def d = file(params.input_dir)
    if (!d.exists() || !d.isDirectory()) cpnfError("--input_dir is not a directory: ${params.input_dir}")

    // Illumination: calculate it (--illum_pipeline), or reuse functions of an earlier run (--illum_dir), not both.
    if (params.illum_pipeline && params.illum_dir)
        cpnfError("set --illum_pipeline (calculate the illumination functions) or --illum_dir (reuse them), not both")
    if (params.illum_pipeline) validatePipelineFile('illum_pipeline')
    if (params.illum_dir && !file(params.illum_dir).isDirectory())
        cpnfError("--illum_dir is not a directory: ${params.illum_dir}")

    // Read each boolean parameter once, so that a value such as 'maybe' stops the run here.
    ['save_masks', 'strict_image_count', 'allow_unpatched', 'gzip_features', 'allow_incomplete_sets',
     'merge_all_plates', 'check_compartments']
        .each { name -> boolParam(name) }

    // Image discovery searches input_dir recursively: outputs or task folders inside it would be
    // read back as input images by a later run (or by this run's own staged links).
    def inputPath = d.toAbsolutePath().normalize()
    def outPath   = file(params.outdir).toAbsolutePath().normalize()
    if (outPath.startsWith(inputPath))
        cpnfError("--outdir ${outPath} is inside --input_dir ${inputPath}. Choose an output folder outside the image folder.")
    def workPath  = workflow.workDir.toAbsolutePath().normalize()
    if (workPath.startsWith(inputPath))
        cpnfError("the work directory ${workPath} is inside --input_dir ${inputPath}. Set -work-dir outside the image folder.")

    // Simple value checks: the chunk size, the mask format, the extensions and the plugin folder.
    if (!params.chunk_size.toString().isInteger() || (params.chunk_size as int) < 0)
        cpnfError("--chunk_size must be an integer >= 0 (0 = all image sets of a plate in one CellProfiler job)")
    if (!(params.mask_format in ['tiff', 'png', 'npy']))
        cpnfError("--mask_format must be one of tiff, png, npy")
    if (!imageExtensions())
        cpnfError("--extensions is empty")
    if (params.plugins_dir && !file(params.plugins_dir).isDirectory())
        cpnfError("--plugins_dir is not a directory: ${params.plugins_dir}")

    // Cores and memory. --total_cpus is the budget of the whole run; one analysis chunk takes --segmentation_cpus.
    ['segmentation_cpus', 'total_cpus', 'max_cpus'].each { name ->
        if (!params[name].toString().isInteger() || (params[name] as int) < 1)
            cpnfError("--${name} must be an integer >= 1, not '${params[name]}'")
    }
    def seg = params.segmentation_cpus as int
    if (seg > (params.total_cpus as int))
        cpnfError("--segmentation_cpus ${seg} is more than --total_cpus ${params.total_cpus}: no chunk could start. " +
            "Raise --total_cpus or lower --segmentation_cpus.")
    if (seg > (params.max_cpus as int))
        cpnfError("--segmentation_cpus ${seg} is more than --max_cpus ${params.max_cpus} (the most cores of one job).")
    ['memory_per_cpu', 'max_memory', 'total_memory'].each { name ->
        if (!params[name]) return
        try { params[name] as nextflow.util.MemoryUnit }
        catch (Exception _e) { cpnfError("--${name} must be a memory size such as '8.GB', not '${params[name]}'") }
    }
    def chunkMemory = chunkMemoryGB()
    if (params.total_memory && chunkMemory > (params.total_memory as nextflow.util.MemoryUnit).toGiga())
        cpnfError("one analysis chunk needs ${chunkMemory} GB (--memory_per_cpu x --segmentation_cpus), " +
            "more than --total_memory ${params.total_memory}")

    // Plugins: each plugin module of a pipeline needs its file in the plugin folder.
    def pluginFiles = [RunCellpose: 'runcellpose.py', EnforceObjectsOneToOne: 'enforceobjectsonetoone.py']
    def modules = pipelineModules(params.pipeline) + (params.illum_pipeline ? pipelineModules(params.illum_pipeline) : [])
    pluginFiles.each { module, fileName ->
        if (!(module in modules)) return
        if (!params.plugins_dir)
            cpnfError("the pipeline uses the plugin module ${module}, but --plugins_dir is not set (default: cp-plugins/ of the repository)")
        if (!file("${params.plugins_dir}/${fileName}").exists())
            cpnfError("the pipeline uses the plugin module ${module}, but ${params.plugins_dir} has no ${fileName}")
    }

    // RunCellpose needs Cellpose in the container. The official CellProfiler image has none.
    if ('RunCellpose' in modules && workflow.containerEngine && params.container.toString().startsWith('cellprofiler/cellprofiler'))
        cpnfError("the pipeline uses RunCellpose, but --container ${params.container} has no Cellpose. " +
            "Use the Cellpose image (containers/cellprofiler-cellpose, see containers/README.md).")

    // Cluster profiles: warn about a missing Slurm account, and apply the Berzelius rules.
    if (workflow.profile.tokenize(',').contains('slurm') && !params.slurm_account)
        log.warn "[cp-headless] -profile slurm without --slurm_account: most clusters reject jobs without an account."
    if (workflow.profile.tokenize(',').contains('berzelius'))
        validateBerzelius()

    // --required_metadata must be a list of names, for example 'Plate,Well,Site'.
    if (params.required_metadata &&!(params.required_metadata.toString() ==~ /\s*\w+(\s*,\s*\w+)*\s*/))
        cpnfError("--required_metadata must be comma-separated metadata names, e.g. 'Plate,Well,Site'")

    // A broken regular expression would otherwise fail later, in the middle of the grouping step.
    ['group_regex', 'plate_regex'].each { name ->
        if (!params[name]) return
        try {
            def pattern = java.util.regex.Pattern.compile(params[name].toString())
            if (name == 'plate_regex' && pattern.matcher('').groupCount() < 1)
                cpnfError("--plate_regex needs a capture group (round brackets) for the plate name, e.g. '^([^/]+)/'")
        }
        catch (java.util.regex.PatternSyntaxException e) { cpnfError("invalid --${name}: ${e.message}") }
    }

    // Without group_regex, each file is one image set. That is wrong for images with several channels.
    if ((params.chunk_size as int) > 0 && !params.group_regex) {
        log.warn """\
            [cp-headless] --chunk_size > 0 without --group_regex: files are split into chunks one by one.
            That is only correct for SINGLE-channel pipelines. For multi-channel image sets set
            --group_regex so all channels of a site land in the same chunk (see README).
            Each chunk checks that CellProfiler made one image set per file.""".stripIndent()
    }
}

// Make the plan of the run from the image sets: for each plate its files, its image sets and its chunks.
// groups: [[plate, image set key], [files]], sorted by plate, then by key. The sort makes the chunks the
// same in each run, which -resume needs. Returns [plates: [plate: [files, sets, channels, chunks]], chunks].
def buildPlan(groups, int chunkSize, groupPattern, boolean allowIncomplete, boolean onCluster) {
    def plates = [:]
    def chunks = []
    def problems = []
    groups.groupBy { g -> g[0][0] }.each { plate, plateGroups ->

        // Image-set integrity, per plate: every file must match group_regex, and every image set must
        // have the same number of files (one per channel). The most common size is taken as the
        // channel count; other sizes mean a missing channel or extra files.
        def unmatched  = plateGroups.findAll { g -> g[0][1].startsWith('__unmatched__/') }
        def matched    = plateGroups.findAll { g -> !g[0][1].startsWith('__unmatched__/') }
        def channels   = 1
        def incomplete = []
        if (groupPattern && matched) {
            channels   = matched.collect { g -> g[1].size() }.countBy { n -> n }.max { e -> e.value }.key
            incomplete = matched.findAll { g -> g[1].size() != channels }
        }
        if (unmatched)
            problems << "plate ${plate}: ${unmatched.size()} file(s) do not match --group_regex, e.g. ${unmatched.take(3).collect { g -> g[1][0] }}"
        if (incomplete)
            problems << "plate ${plate}: ${incomplete.size()} image set(s) do not have ${channels} file(s), e.g. " +
                incomplete.take(3).collect { g -> "${g[0][1]} -> ${g[1]}" }.join('; ')

        // Cut the sorted image sets of the plate into chunks of chunk_size (0 = one chunk with all of them).
        // A chunk never splits an image set, and never holds sites of two plates.
        def batches = chunkSize > 0 ? plateGroups.collate(chunkSize) : [plateGroups]
        if (onCluster && chunkSize == 0 && plateGroups.size() > 500)
            log.warn "[cp-headless] plate ${plate}: ${plateGroups.size()} image sets run as ONE cluster job (--chunk_size 0). " +
                "Set --chunk_size so that one job takes 15-60 min: one job can not run longer than the wall-time limit."
        def width = Math.max(4, batches.size().toString().length())
        batches.eachWithIndex { batch, i ->
            chunks << tuple(plate, "${plate}_chunk_${(i + 1).toString().padLeft(width, '0')}".toString(),
                batch.collectMany { g -> g[1] }, batch.size())
        }
        plates[plate] = [files: plateGroups.collectMany { g -> g[1] }, sets: plateGroups.size(),
                         channels: channels, chunks: batches.size()]
    }

    // Stop with examples, or only warn if the user set --allow_incomplete_sets true.
    if (problems && allowIncomplete) {
        log.warn "[cp-headless] ${problems.join('\n')}\n" +
            "Continuing because --allow_incomplete_sets is true: unmatched files become their own image sets."
    } else if (problems) {
        cpnfError("${problems.join('\n')}\n" +
            "Fix --group_regex or --extensions, or remove the files. " +
            "Set --allow_incomplete_sets true to process them anyway.")
    }
    return [plates: plates, chunks: chunks]
}

// Show the plan: per plate the image sets, the files and the chunks with their cores and memory.
// One message with one line per plate, so that the lines stay together in the log.
def logPlan(plan) {
    def seg = params.segmentation_cpus as int
    def sets = plan.plates.values().sum { p -> p.sets }
    def files = plan.plates.values().sum { p -> p.files.size() }
    def lines = ["[cp-headless] ${plan.plates.size()} plate(s): ${sets} image set(s), ${files} file(s) -> ${plan.chunks.size()} chunk(s)"]
    plan.plates.each { plate, p ->
        lines << "[cp-headless] ${plate}: ${p.sets} image set(s) of ${p.channels} file(s), " +
            "${p.chunks} chunks x ${seg} cores x ${chunkMemoryGB()} GB"
    }
    if (plan.plates.size() > 1 && !params.required_metadata)
        lines << "[cp-headless] ${plan.plates.size()} plates: set --required_metadata 'Plate,Well,Site' to check in each " +
            "chunk that every site has a plate, well and site, and that no site occurs twice."
    log.info lines.join('\n')
}

// Provenance for every run: which code, Nextflow, container and parameters made these results.
// The CellProfiler version that ran is in pipeline/patch_report.json.
def gitCommit() {

    // A run from GitHub (nextflow run <repo> -r <tag>) knows its commit. A run from a local folder asks git.
    // "-dirty" means that the folder had changes that were not committed.
    if (workflow.commitId) return workflow.commitId
    try {
        def proc = ['git', '-C', projectDir.toString(), 'rev-parse', 'HEAD'].execute()
        proc.waitFor()
        if (proc.exitValue() != 0) return null
        def dirty = ['git', '-C', projectDir.toString(), 'status', '--porcelain', '--untracked-files=no'].execute()
        dirty.waitFor()
        return proc.text.trim() + (dirty.text.trim() ? '-dirty' : '')
    } catch (Exception _e) {
        return null
    }
}

// Write <outdir>/pipeline_info/run_info.json: the code version, the run, Nextflow, the containers, all
// parameters and, when the images are found (plan), the plates with their sites and chunks.
// With this file, someone can later find out how the results were made.
def writeRunInfo(plan) {
    def info = [
        workflow : [name: workflow.manifest.name, version: workflow.manifest.version,
                    git_commit: gitCommit(), repository: workflow.repository, revision: workflow.revision,
                    project_dir: projectDir.toString()],
        run      : [name: workflow.runName, session_id: workflow.sessionId.toString(),
                    start: workflow.start.toString(), profile: workflow.profile, resume: workflow.resume,
                    stub_run: workflow.stubRun, command_line: workflow.commandLine],
        nextflow : nextflow.version.toString(),
        container: params.container,
        illumination: params.illum_pipeline ? 'run' : (params.illum_dir ? 'reuse' : 'none'),
        params   : params.collectEntries { k, v -> [(k): v?.toString()] },
    ]
    if (plan) {
        info.plates = plan.plates.collectEntries { plate, p ->
            [(plate): [sites: p.sets, files: p.files.size(), files_per_site: p.channels, chunks: p.chunks]]
        }
    }
    def dir = file("${params.outdir}/pipeline_info")
    dir.mkdirs()
    file("${dir}/run_info.json").text = groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(info))
}

// The illumination functions of a plate from --illum_dir: <illum_dir>/<plate>/illum/*.npy (the layout of the
// results of this workflow) or <illum_dir>/<plate>/*.npy. Each plate needs one file per channel.
def reusedIllum(illumDir, String plate, int channels) {
    def dirs = [file("${illumDir}/${plate}/illum"), file("${illumDir}/${plate}")].findAll { dir -> dir.isDirectory() }
    def files = dirs ? dirs[0].listFiles().findAll { f -> f.name.toLowerCase().endsWith('.npy') }.sort { f -> f.name } : []
    if (!files)
        cpnfError("--illum_dir ${illumDir}: no .npy files for plate ${plate} (looked in ${plate}/illum/ and ${plate}/)")
    if (files.size() != channels)
        cpnfError("--illum_dir ${illumDir}: plate ${plate} has ${files.size()} illumination function(s), " +
            "expected ${channels} (one per channel): ${files*.name}")
    return files
}

// ------------------------------------------------------------------ processes

// Each process below is one type of job. Nextflow runs each job in its own folder in work/,
// inside the CellProfiler container. The scripts in bin/ are on the PATH of each job.
//
// The "stub:" blocks replace the real script during `-stub-run`. They make small fake files, so
// that the tests can check how the jobs connect without running CellProfiler.

// PATCH_PIPELINE runs once per pipeline (kind 'analysis', and 'illum' with --illum_pipeline). It opens the
// pipeline with CellProfiler itself and makes it safe for headless runs. The analysis pipeline gets mask
// saving and a spreadsheet export with one table per object (Image.csv, Cells.csv, ...), loses CreateBatchFiles,
// and sends all outputs to the job folder. The illumination pipeline must calculate the functions and save them as .npy files.
// patch_report.json lists each change.
process PATCH_PIPELINE {
    tag "${kind}: ${cppipe.name}"
    label 'cellprofiler'
    publishDir "${params.outdir}/pipeline", mode: params.publish_mode

    input:
    tuple val(kind), path(cppipe, stageAs: 'original/*')
    path plugins, stageAs: 'plugins'

    output:
    tuple val(kind), path("${kind == 'illum' ? 'illum_' : ''}patched.cppipe"),
        path("${kind == 'illum' ? 'illum_' : ''}patch_report.json"), emit: patched

    script:

    // Turn the workflow parameters into options for bin/patch_cppipe.py.
    def prefix = kind == 'illum' ? 'illum_' : ''
    def args = []
    if (kind == 'illum') {
        args << '--illum --no-masks'
    } else {
        if (!boolParam('save_masks'))       args << '--no-masks'
        if (params.mask_objects)            args << "--objects '${params.mask_objects}'"
        if ((params.chunk_size as int) > 0) args << '--chunked'
        if (params.illum_pipeline || params.illum_dir) args << '--illum-files'
    }
    if (boolParam('allow_unpatched')) args << '--allow-unpatched'
    if (plugins)                      args << '--plugins-dir "$PWD/plugins"'
    """
    export HOME="\$PWD" MPLCONFIGDIR="\$PWD/.mpl" QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg PYTHONNOUSERSITE=1
    patch_cppipe.py \\
        --input "${cppipe}" \\
        --output ${prefix}patched.cppipe \\
        --report ${prefix}patch_report.json \\
        --mask-format ${params.mask_format} \\
        ${args.join(' ')}
    """

    stub:
    def prefix = kind == 'illum' ? 'illum_' : ''
    def report = kind == 'illum'
        ? '{"illum": true, "illum_outputs": [{"image": "IllumDNA", "file_name": "IllumDNA"}]}'
        : '{"objects": ["Nuclei"], "mask_reference_image": "DNA", "masks_added": [{"object": "Nuclei", "suffix": "_Nuclei_mask", "format": "tiff"}], "masks_managed": [{"object": "Nuclei", "suffix": "_Nuclei_mask", "format": "tiff"}]}'
    """
    cp "${cppipe}" ${prefix}patched.cppipe
    echo '${report}' > ${prefix}patch_report.json
    """
}

// ILLUM runs once per plate, on all images of the plate in one job (never in chunks): the illumination
// pipeline averages over all images. bin/check_illum.py then checks the functions: one .npy file per
// SaveImages module, finite values, minimum > 0. The functions of a plate go to <outdir>/<plate>/illum/.
process ILLUM {
    tag "${plate} (${relpaths.size()} files)"
    label 'cellprofiler'
    publishDir path: { "${params.outdir}/${plate}" }, mode: params.publish_mode, pattern: 'illum/*.npy'
    publishDir "${params.outdir}/logs", mode: params.publish_mode, pattern: '{log,qc}_*'

    // plate: the plate name. relpaths: all image files of the plate, relative to input_dir.
    // channels: files per image set (for a warning if it differs from the number of functions).
    input:
    tuple val(plate), val(relpaths), val(channels)
    path pipeline
    path patch_report
    path input_dir, stageAs: 'input'
    path plugins, stageAs: 'plugins'

    output:
    tuple val(plate), path('illum/*.npy'), emit: npy
    path "log_illum_${plate}.txt",         emit: log
    path "qc_illum_${plate}.json",         emit: qc

    script:
    def pluginArg = plugins ? '--plugins-directory "$PWD/plugins"' : ''
    """
    set -euo pipefail

    # Same environment as the analysis chunks: writable HOME and temp, no display, no user packages.
    export HOME="\$PWD" MPLCONFIGDIR="\$PWD/.mpl" TMPDIR="\$PWD/tmp"
    export QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg PYTHONNOUSERSITE=1
    export OMP_NUM_THREADS=${task.cpus} OPENBLAS_NUM_THREADS=${task.cpus} MKL_NUM_THREADS=${task.cpus}
    mkdir -p "\$TMPDIR" out

    # File list: all images of the plate, through the staged 'input' link.
    cat > rel_paths.txt <<'__CPNF_FILES__'
${relpaths.join('\n')}
__CPNF_FILES__
    awk -v root="\$PWD/input/" 'NF { print root \$0 }' rel_paths.txt > file_list.txt

    cellprofiler -c -r \\
        -p "${pipeline}" \\
        --file-list file_list.txt \\
        -i "\$PWD/input" \\
        -o "\$PWD/out" \\
        -t "\$TMPDIR" \\
        ${pluginArg} ${params.cellprofiler_args} \\
        2>&1 | tee "log_illum_${plate}.txt"

    # CellProfiler can end with exit code 0 after errors. check_illum.py checks the functions and copies them to illum/.
    check_illum.py \\
        --outdir out \\
        --log "log_illum_${plate}.txt" \\
        --patch-report "${patch_report}" \\
        --dest illum \\
        --channels ${channels} \\
        --qc "qc_illum_${plate}.json"
    """

    stub:
    """
    mkdir -p illum
    echo "${plate}" > illum/IllumDNA.npy
    touch "log_illum_${plate}.txt"
    echo '{"plate": "${plate}"}' > "qc_illum_${plate}.json"
    """
}

// CELLPROFILER runs once per chunk, and the chunks run at the same time (as many as --total_cpus allows).
// Each job runs CellProfiler on the files of its chunk plus the illumination functions of its plate, then
// bin/check_chunk.py checks the result. The check stops the job if image sets, tables, masks or
// metadata are missing or wrong.
process CELLPROFILER {
    tag "${chunk_id} (${n_sets} sets, ${relpaths.size()} files)"
    label 'cellprofiler'

    // masks: results/<plate>/masks/<sub-folders below the plate folder>/<image>_<Object>_mask.tiff
    // anything else your own .cppipe saves (overlays, crops, ...) -> <plate>/cellprofiler_outputs/<chunk>/...
    // The tables are not published here: MERGE_FEATURES publishes the merged tables.
    publishDir "${params.outdir}", mode: params.publish_mode, pattern: '*_chunk_*/**',
        saveAs: { fn -> fn.toLowerCase().endsWith('.csv') ? null : publishedChunkPath(fn) }
    publishDir "${params.outdir}/logs", mode: params.publish_mode, pattern: '{log,qc}_*'

    // plate: the plate of the chunk. chunk_id: for example PANC1_P01_chunk_0003. relpaths: the image files of
    // the chunk, relative to input_dir. n_sets: the number of image sets that the workflow expects in the chunk.
    // illum_files: the illumination functions of this plate only (empty without illumination).
    // input_dir: the complete image folder, linked into the job folder as 'input'.
    input:
    tuple val(plate), val(chunk_id), val(relpaths), val(n_sets), path(illum_files, stageAs: 'illum/*')
    path pipeline
    path patch_report
    path input_dir, stageAs: 'input'
    path plugins, stageAs: 'plugins'

    output:

    // NB: do not declare the "${chunk_id}" directory itself as an output - Nextflow then
    // skips publishing the files nested in it (masks would silently not be published).
    tuple val(plate), path("features_${chunk_id}", type: 'dir'), emit: features
    tuple val(plate), val(chunk_id), path("${chunk_id}/masks/**"), optional: true, emit: masks
    path "${chunk_id}/**", optional: true,        emit: files
    path "log_${chunk_id}.txt",                   emit: log
    path "qc_${chunk_id}.json",                   emit: qc

    script:
    def pluginArg = plugins ? '--plugins-directory "$PWD/plugins"' : ''

    // With chunking, every chunk must hold whole image sets: compare CellProfiler's count with ours.
    // The illumination functions add no image set: NamesAndTypes gives the same function to every site.
    def expected  = (params.group_regex || (params.chunk_size as int) > 0) ? n_sets : -1
    def strict    = boolParam('strict_image_count') ? '--strict' : ''
    def requiredMetadata = params.required_metadata ? "--required-metadata '${params.required_metadata}'" : ''
    """
    set -euo pipefail

    # CellProfiler/matplotlib write settings into \$HOME; containers often have none.
    export HOME="\$PWD" MPLCONFIGDIR="\$PWD/.mpl" TMPDIR="\$PWD/tmp"

    # No display on cluster nodes: keep Qt and matplotlib from looking for one.
    export QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg

    # Apptainer binds the host home: never load the user's own Python packages into CellProfiler.
    export PYTHONNOUSERSITE=1

    # In containers numpy/Java/PyTorch see the HOST's cores and oversubscribe; pin to what we were given
    # (--segmentation_cpus). Cellpose runs PyTorch with exactly these cores.
    export OMP_NUM_THREADS=${task.cpus} OPENBLAS_NUM_THREADS=${task.cpus} MKL_NUM_THREADS=${task.cpus}

    # Cellpose: the models of the container (never a download on a compute node), and a writable cache for
    # the numba functions of Cellpose (the container is read-only under Apptainer).
    export CELLPOSE_LOCAL_MODELS_PATH="\${CELLPOSE_LOCAL_MODELS_PATH:-/opt/cellpose/models}"
    export NUMBA_CACHE_DIR="\$PWD/.numba"
    mkdir -p "\$TMPDIR" "${chunk_id}"

    # File list for this chunk. Paths go through the staged 'input' link so the original
    # folder structure (and any folder-name metadata) is preserved.
    cat > rel_paths.txt <<'__CPNF_FILES__'
${relpaths.join('\n')}
__CPNF_FILES__
    awk -v root="\$PWD/input/" 'NF { print root \$0 }' rel_paths.txt > file_list.txt

    # The illumination functions of this plate come after the images. NamesAndTypes assigns them by name
    # (for example IllumDNA.npy), as in the CellProfiler program.
    for npy in illum/*.npy; do
        if [ -e "\$npy" ]; then echo "\$PWD/\$npy" >> file_list.txt; fi
    done

    # Stop early, with a clear message, if the job cannot read its images (for example a missing
    # container mount). Otherwise CellProfiler fails later with a less clear error.
    unreadable=0
    while IFS= read -r f; do
        [ -r "\$f" ] || { echo "Cannot read: \$f" >&2; unreadable=\$((unreadable + 1)); }
    done < file_list.txt
    if [ "\$unreadable" -gt 0 ]; then
        echo "\$unreadable input file(s) are not readable (container mounts? permissions?)" >&2
        exit 2
    fi

    # Run CellProfiler: -c = no window, -r = run at once. The log goes to the screen and to a file.
    # --file-list takes precedence over -i; -i only sets the Default Input Folder, which the
    # injected mask writer uses to mirror sub-folders.
    cellprofiler -c -r \\
        -p "${pipeline}" \\
        --file-list file_list.txt \\
        -i "\$PWD/input" \\
        -o "\$PWD/${chunk_id}" \\
        -t "\$TMPDIR" \\
        ${pluginArg} ${params.cellprofiler_args} \\
        2>&1 | tee "log_${chunk_id}.txt"

    # CellProfiler can end with exit code 0 after errors. check_chunk.py checks the outputs, copies the
    # tables to features_<chunk>/ with the plate in each row, makes the mask list, and writes qc_<chunk>.json.
    check_chunk.py \\
        --outdir "${chunk_id}" \\
        --log "log_${chunk_id}.txt" \\
        --patch-report "${patch_report}" \\
        --expected-sets ${expected} \\
        --input-dir "\$PWD/input" \\
        --features-dir "features_${chunk_id}" \\
        --manifest "features_${chunk_id}/mask_manifest.csv" \\
        --plate "${plate}" \\
        --illum-dir "\$PWD/illum" \\
        --qc "qc_${chunk_id}.json" ${strict} ${requiredMetadata}
    """

    stub:
    def ids = 'ImageNumber,ObjectNumber,Metadata_Plate,Metadata_Well,Metadata_Site,Number_Object_Number'
    """
    mkdir -p "${chunk_id}/masks/stub" "features_${chunk_id}"
    printf 'ImageNumber,Metadata_Plate,Metadata_Well,Metadata_Site,Count_Nuclei,FileName_DNA,PathName_DNA\\n1,${plate},A01,${chunk_id}_s1,1,image_1.tif,stub\\n2,${plate},A01,${chunk_id}_s2,1,image_2.tif,stub\\n' > "features_${chunk_id}/Image.csv"
    printf '${ids},AreaShape_Area\\n1,1,${plate},A01,${chunk_id}_s1,1,100\\n2,1,${plate},A01,${chunk_id}_s2,1,90\\n' > "features_${chunk_id}/Cells.csv"
    printf '${ids},AreaShape_Area,Parent_Cells\\n1,1,${plate},A01,${chunk_id}_s1,1,50,1\\n2,1,${plate},A01,${chunk_id}_s2,1,40,1\\n' > "features_${chunk_id}/Nuclei.csv"
    printf '${ids},AreaShape_Area,Parent_Cells,Parent_Nuclei\\n1,1,${plate},A01,${chunk_id}_s1,1,50,1,1\\n2,1,${plate},A01,${chunk_id}_s2,1,50,1,1\\n' > "features_${chunk_id}/Cytoplasm.csv"
    printf 'ImageNumber,Metadata_Plate,FileName_DNA,PathName_DNA,InputPath_DNA,MaskObject,MaskPath\\n1,${plate},image_1.tif,stub,stub/image_1.tif,Nuclei,${plate}/masks/stub/${chunk_id}_image_1_Nuclei_mask.tiff\\n2,${plate},image_2.tif,stub,stub/image_2.tif,Nuclei,${plate}/masks/stub/${chunk_id}_image_2_Nuclei_mask.tiff\\n' > "features_${chunk_id}/mask_manifest.csv"
    touch "${chunk_id}/masks/stub/${chunk_id}_image_1_Nuclei_mask.tiff"
    touch "${chunk_id}/masks/stub/${chunk_id}_image_2_Nuclei_mask.tiff" "log_${chunk_id}.txt"

    # For the tests: the plate of the chunk, the plates of its illumination functions, and its cores.
    illum_plates=\$(cat illum/*.npy 2>/dev/null | sort -u | tr '\\n' ' ' || true)
    echo "{\\"plate\\": \\"${plate}\\", \\"illum_from\\": \\"\$illum_plates\\", \\"cpus\\": ${task.cpus}}" > "qc_${chunk_id}.json"
    """
}

// MERGE_FEATURES runs once for all plates (--merge_all_plates true, the default), or once per plate. It joins
// each table of the chunks into one table, and makes ImageNumber unique: CellProfiler starts it at 1 in each
// chunk. CPNF_Chunk and CPNF_ChunkImageNumber keep the original values.
process MERGE_FEATURES {
    tag "${name}"
    label 'merge'
    publishDir path: { "${params.outdir}/${subdir}" }, mode: params.publish_mode

    // name: 'all_plates' or the plate. subdir: the folder of the tables below outdir.
    input:
    tuple val(name), val(subdir), path(chunk_dirs)

    output:
    tuple val(name), path('*.csv{,.gz}'), emit: tables
    path 'merge_report.json',             emit: report

    script:

    // The same site twice is an error: with --required_metadata, or with --check_compartments by plate, well
    // and site.
    def compartments = boolParam('check_compartments')
    def keys         = params.required_metadata ?: (compartments ? 'Plate,Well,Site' : '')
    def unique       = keys ? "--unique-metadata '${keys}'" : ''
    """
    merge_features.py --outdir . --require-plate ${compartments ? '--check-compartments' : ''} \\
        ${boolParam('gzip_features') ? '--gzip' : ''} ${unique} ${chunk_dirs}
    """
}

// ------------------------------------------------------------------ workflow

// The main workflow: check the parameters, find the images and group them into plates and chunks, then
// connect the jobs.
workflow {
    validateParams()

    // Values that the steps below use.
    def inputDir     = file(params.input_dir).toAbsolutePath().normalize()
    def exts         = imageExtensions()
    def chunkSize    = params.chunk_size as int
    def groupPattern = params.group_regex ? java.util.regex.Pattern.compile(params.group_regex.toString()) : null
    def plateRegex   = params.plate_regex ? java.util.regex.Pattern.compile(params.plate_regex.toString()) : null
    def plugins      = params.plugins_dir ? file(params.plugins_dir) : []
    def allowIncomplete = boolParam('allow_incomplete_sets')
    def onCluster    = workflow.profile.tokenize(',').any { p -> p in ['slurm', 'berzelius'] }
    def illumMode    = params.illum_pipeline ? 'run (--illum_pipeline)' : (params.illum_dir ? "reuse ${params.illum_dir}" : 'none')
    def mergeAll     = boolParam('merge_all_plates')
    def seg          = params.segmentation_cpus as int
    def atOnce       = (params.total_cpus as int).intdiv(seg)

    // Show the most important settings at the start of the log. The plates and their chunks follow when the
    // images are found.
    log.info """\
        ==================================  cp-headless  ==================================
        pipeline       : ${params.pipeline}
        illumination   : ${illumMode}
        input_dir      : ${inputDir}
        plates         : ${plateRegex ? "--plate_regex ${params.plate_regex}" : 'first folder below input_dir'}
        outdir         : ${params.outdir}
        group_regex    : ${params.group_regex ?: '(none: every file is its own image set)'}
        chunk_size     : ${chunkSize ?: 'all image sets of a plate in one job'}
        cores          : ${seg} per chunk, ${params.total_cpus} in total -> ${atOnce} chunk(s) at once
        merge          : ${mergeAll ? 'all plates into one table' : 'one table per plate'}
        save_masks     : ${boolParam('save_masks')} (${params.mask_format})
        container      : ${params.container}
        =================================================================================
        """.stripIndent()

    writeRunInfo(null)

    // 1. discover images (recursive, case-insensitive extension match, hidden files skipped)
    // Each file becomes its path relative to input_dir, for example "plate1/A01_s1_w1.tif".
    ch_images = channel
        .fromPath("${inputDir}/**", type: 'file')
        .filter { f ->
            def n = f.name.toLowerCase()
            exts.any { ext -> n.endsWith(".${ext}") }
        }
        .map { f -> inputDir.relativize(f).toString() }
        .ifEmpty { cpnfError("no files with extensions [${exts.join(', ')}] found under ${inputDir}") }

    // 2. the plan: give each file its plate and its image set, check the image sets of each plate, and cut
    // each plate into chunks. The sort (plate, then image set) makes the chunks the same in each run.
    ch_plan = ch_images
        .map { rel ->
            def plate = plateOf(rel, plateRegex)
            if (plate == null)
                cpnfError("${rel} has no plate: " + (plateRegex ? "--plate_regex does not match its path" :
                    "put the images of each plate into their own folder below --input_dir (or set --plate_regex)"))
            if (!(plate ==~ plateNamePattern()))
                cpnfError("plate name '${plate}' (from ${rel}) may only have letters, digits, '.', '_' and '-'")
            if (plate in reservedPlateNames())
                cpnfError("plate name '${plate}' is also the name of a results folder. Rename the plate folder.")
            tuple([plate, imageSetOf(rel, groupPattern)], rel)
        }
        .groupTuple(sort: true)
        .toSortedList { a, b -> (a[0][0] <=> b[0][0]) ?: (a[0][1] <=> b[0][1]) }
        .map { groups -> buildPlan(groups, chunkSize, groupPattern, allowIncomplete, onCluster) }
    ch_plan.subscribe { plan ->
        logPlan(plan)
        writeRunInfo(plan)
    }
    ch_chunks       = ch_plan.flatMap { plan -> plan.chunks }       // [plate, chunk_id, files, n_sets]
    ch_plate_files  = ch_plan.flatMap { plan -> plan.plates.collect { plate, p -> tuple(plate, p.files, p.channels) } }
    ch_plate_chunks = ch_plan.flatMap { plan -> plan.plates.collect { plate, p -> tuple(plate, p.chunks) } }

    // 3. patch each pipeline once. All ILLUM and chunk jobs get the same patched pipelines.
    ch_pipelines = channel.of(tuple('analysis', file(params.pipeline)))
    if (params.illum_pipeline)
        ch_pipelines = ch_pipelines.mix(channel.of(tuple('illum', file(params.illum_pipeline))))
    PATCH_PIPELINE(ch_pipelines, plugins)
    ch_patched = PATCH_PIPELINE.out.patched.branch { kind, _cppipe, _report ->
        illum: kind == 'illum'
        analysis: true
    }

    // 4. the illumination functions of each plate: calculate them (ILLUM, one job per plate), reuse them
    // (--illum_dir), or none. All ILLUM jobs can start at once; a plate's chunks wait for its own ILLUM job only.
    if (params.illum_pipeline) {
        ILLUM(ch_plate_files,
            ch_patched.illum.map { _kind, cppipe, _report -> cppipe }.first(),
            ch_patched.illum.map { _kind, _cppipe, report -> report }.first(),
            inputDir, plugins)
        ch_illum = ILLUM.out.npy
    } else if (params.illum_dir) {
        def illumDir = file(params.illum_dir).toAbsolutePath().normalize()
        ch_illum = ch_plan.flatMap { plan ->
            plan.plates.collect { plate, p -> tuple(plate, reusedIllum(illumDir, plate, p.channels)) }
        }
    } else {
        ch_illum = channel.empty()
    }

    // 5. run every chunk with the functions of its own plate: combine by plate key, so a chunk can not get
    // the .npy files of another plate. Without illumination, the chunk gets an empty list.
    def withIllum = params.illum_pipeline || params.illum_dir
    ch_chunk_jobs = withIllum ? ch_chunks.combine(ch_illum, by: 0) : ch_chunks.map { plate, chunk_id, files, n -> tuple(plate, chunk_id, files, n, []) }
    CELLPROFILER(ch_chunk_jobs,
        ch_patched.analysis.map { _kind, cppipe, _report -> cppipe }.first(),
        ch_patched.analysis.map { _kind, _cppipe, report -> report }.first(),
        inputDir, plugins)

    // 6. merge: once for all plates (default), or once per plate as soon as all chunks of that plate are done
    // (groupKey tells groupTuple how many chunks to wait for).
    if (mergeAll) {
        ch_merge = CELLPROFILER.out.features
            .map { _plate, dir -> dir }
            .collect(sort: true)
            .map { dirs -> tuple('all_plates', 'cellprofiler_tables', dirs) }
    } else {
        ch_merge = CELLPROFILER.out.features
            .combine(ch_plate_chunks, by: 0)
            .map { plate, dir, n -> tuple(groupKey(plate, n), dir) }
            .groupTuple(sort: true)
            .map { key, dirs -> tuple(key.toString(), "${key}/cellprofiler_tables".toString(), dirs) }
    }
    MERGE_FEATURES(ch_merge)

    // 7. cross-chunk sanity check: two chunks writing the same mask path would overwrite on publish
    // This step only warns early. MERGE_FEATURES makes the same check and stops the run.
    CELLPROFILER.out.masks
        .flatMap { _plate, chunk_id, files ->
            (files instanceof List ? files : [files]).collect { f ->
                def s = f.toString()
                def marker = "/${chunk_id}/masks/"
                publishedChunkPath("${chunk_id}/masks/${s.substring(s.indexOf(marker) + marker.length())}")
            }
        }
        .toList()
        .subscribe { paths ->
            def dups = paths.countBy { p -> p }.findAll { e -> e.value > 1 }
            if (dups)
                log.warn "[cp-headless] ${dups.size()} mask path collision(s) detected, e.g. ${dups.keySet().take(3)}; MERGE_FEATURES will fail the run."
        }
}
