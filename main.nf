#!/usr/bin/env nextflow
/*
 * cp-headless
 * ---------------
 * Headless CellProfiler on a folder of images, from just:
 *   --pipeline  my_pipeline.cppipe   (or .cpproj)
 *   --input_dir /path/to/images
 *   (+ your nextflow config)
 *
 * Produces merged per-image / per-object feature tables, a channel-to-mask
 * manifest, and uint16 label masks for every object set.
 */
nextflow.enable.dsl = 2

// ------------------------------------------------------------------ helpers
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

def imageExtensions() {
    params.extensions.toString().tokenize(',')
        .collect { ext -> ext.trim().toLowerCase().replaceFirst(/^\./, '') }
        .findAll { ext -> ext }
}

def inHomeDir(path) {
    def home = System.getenv('HOME')
    if (!home || path == null) return false
    def abs = file(path.toString()).toAbsolutePath().normalize()
    return abs.startsWith(file(home).toAbsolutePath().normalize())
}

// Berzelius site rules (see conf/berzelius.config). They stop the run before any job is submitted.
def validateBerzelius() {
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

def validateParams() {
    if (!params.pipeline)  cpnfError("--pipeline is required (path to a .cppipe or .cpproj file)")
    if (!params.input_dir) cpnfError("--input_dir is required (folder containing your images)")

    def p = file(params.pipeline)
    if (!p.exists() || p.isDirectory()) cpnfError("pipeline file not found: ${params.pipeline}")
    if (!(p.name.toLowerCase() ==~ /.*\.(cppipe|cpproj)$/))
        log.warn "[cellprofiler-nf] '${p.name}' does not end in .cppipe/.cpproj - trying anyway"

    def d = file(params.input_dir)
    if (!d.exists() || !d.isDirectory()) cpnfError("--input_dir is not a directory: ${params.input_dir}")

    ['save_masks', 'strict_image_count', 'allow_unpatched', 'gzip_features', 'allow_incomplete_sets']
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

    if (!params.chunk_size.toString().isInteger() || (params.chunk_size as int) < 0)
        cpnfError("--chunk_size must be an integer >= 0 (0 = all images in one CellProfiler job)")
    if (!(params.mask_format in ['tiff', 'png', 'npy']))
        cpnfError("--mask_format must be one of tiff, png, npy")
    if (!imageExtensions())
        cpnfError("--extensions is empty")
    if (params.plugins_dir && !file(params.plugins_dir).isDirectory())
        cpnfError("--plugins_dir is not a directory: ${params.plugins_dir}")
    if (workflow.profile.tokenize(',').contains('slurm') && !params.slurm_account)
        log.warn "[cp-headless] -profile slurm without --slurm_account: most clusters reject jobs without an account."
    if (workflow.profile.tokenize(',').contains('berzelius'))
        validateBerzelius()
    if (params.required_metadata &&!(params.required_metadata.toString() ==~ /\s*\w+(\s*,\s*\w+)*\s*/))
        cpnfError("--required_metadata must be comma-separated metadata names, e.g. 'Plate,Well,Site'")
    if (params.group_regex) {
        try { java.util.regex.Pattern.compile(params.group_regex.toString()) }
        catch (Exception e) { cpnfError("invalid --group_regex: ${e.message}") }
    }
    if ((params.chunk_size as int) > 0 && !params.group_regex) {
        log.warn """\
            [cp-headless] --chunk_size > 0 without --group_regex: files are split into chunks one by one.
            That is only correct for SINGLE-channel pipelines. For multi-channel image sets set
            --group_regex so all channels of a site land in the same chunk (see README).
            Each chunk checks that CellProfiler made one image set per file.""".stripIndent()
    }
}

// Provenance for every run: which code, Nextflow, container and parameters made these results.
// The CellProfiler version that ran is in pipeline/patch_report.json.
def gitCommit() {
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

def writeRunInfo() {
    def info = [
        workflow : [name: workflow.manifest.name, version: workflow.manifest.version,
                    git_commit: gitCommit(), repository: workflow.repository, revision: workflow.revision,
                    project_dir: projectDir.toString()],
        run      : [name: workflow.runName, session_id: workflow.sessionId.toString(),
                    start: workflow.start.toString(), profile: workflow.profile, resume: workflow.resume,
                    stub_run: workflow.stubRun, command_line: workflow.commandLine],
        nextflow : nextflow.version.toString(),
        container: params.container,
        params   : params.collectEntries { k, v -> [(k): v?.toString()] },
    ]
    def dir = file("${params.outdir}/pipeline_info")
    dir.mkdirs()
    file("${dir}/run_info.json").text = groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(info))
}

// ------------------------------------------------------------------ processes
process PATCH_PIPELINE {
    tag "${cppipe.name}"
    label 'cellprofiler'
    publishDir "${params.outdir}/pipeline", mode: params.publish_mode

    input:
    path cppipe, stageAs: 'original/*'
    path plugins, stageAs: 'plugins'

    output:
    path 'patched.cppipe',    emit: pipeline
    path 'patch_report.json', emit: report

    script:
    def args = []
    if (!boolParam('save_masks'))     args << '--no-masks'
    if (params.mask_objects)          args << "--objects '${params.mask_objects}'"
    if (boolParam('allow_unpatched')) args << '--allow-unpatched'
    if ((params.chunk_size as int) > 0) args << '--chunked'
    if (plugins)               args << '--plugins-dir "$PWD/plugins"'
    """
    export HOME="\$PWD" MPLCONFIGDIR="\$PWD/.mpl" QT_QPA_PLATFORM=offscreen MPLBACKEND=Agg PYTHONNOUSERSITE=1
    patch_cppipe.py \\
        --input "${cppipe}" \\
        --output patched.cppipe \\
        --report patch_report.json \\
        --mask-format ${params.mask_format} \\
        ${args.join(' ')}
    """

    stub:
    """
    cp "${cppipe}" patched.cppipe
    echo '{"objects": ["Nuclei"], "mask_reference_image": "DNA", "masks_added": [{"object": "Nuclei", "suffix": "_Nuclei_mask", "format": "tiff"}], "masks_managed": [{"object": "Nuclei", "suffix": "_Nuclei_mask", "format": "tiff"}]}' > patch_report.json
    """
}

process CELLPROFILER {
    tag "${chunk_id} (${n_sets} sets, ${relpaths.size()} files)"
    label 'cellprofiler'

    // masks keep the input folder structure: results/masks/<subdir>/<image>_<Object>_mask.tiff
    publishDir "${params.outdir}", mode: params.publish_mode, pattern: 'chunk_*/masks/**',
        saveAs: { fn -> fn.replaceFirst(/^[^\/]+\/masks\//, 'masks/') }
    publishDir "${params.outdir}/logs", mode: params.publish_mode, pattern: '{log,qc}_*'
    // anything else your own .cppipe saves (overlays, crops, ...) -> cellprofiler_outputs/<chunk>/...
    publishDir "${params.outdir}/cellprofiler_outputs", mode: params.publish_mode, pattern: 'chunk_*/**',
        saveAs: { fn -> (fn ==~ /^[^\/]+\/masks\/.*/ || fn.toLowerCase().endsWith('.csv')) ? null : fn }

    input:
    tuple val(chunk_id), val(relpaths), val(n_sets)
    path pipeline
    path patch_report
    path input_dir, stageAs: 'input'
    path plugins, stageAs: 'plugins'

    output:
    // NB: do not declare the "${chunk_id}" directory itself as an output - Nextflow then
    // skips publishing the files nested in it (masks would silently not be published).
    path "features_${chunk_id}", type: 'dir',     emit: features
    tuple val(chunk_id), path("${chunk_id}/masks/**"), optional: true, emit: masks
    path "${chunk_id}/**", optional: true,        emit: files
    path "log_${chunk_id}.txt",                   emit: log
    path "qc_${chunk_id}.json",                   emit: qc

    script:
    def pluginArg = plugins ? '--plugins-directory "$PWD/plugins"' : ''
    // With chunking, every chunk must hold whole image sets: compare CellProfiler's count with ours.
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
    # In containers numpy/Java see the HOST's cores and oversubscribe; pin to what we were given.
    export OMP_NUM_THREADS=${task.cpus} OPENBLAS_NUM_THREADS=${task.cpus} MKL_NUM_THREADS=${task.cpus}
    mkdir -p "\$TMPDIR" "${chunk_id}"

    # File list for this chunk. Paths go through the staged 'input' link so the original
    # folder structure (and any folder-name metadata) is preserved.
    cat > rel_paths.txt <<'__CPNF_FILES__'
${relpaths.join('\n')}
__CPNF_FILES__
    awk -v root="\$PWD/input/" 'NF { print root \$0 }' rel_paths.txt > file_list.txt

    unreadable=0
    while IFS= read -r f; do
        [ -r "\$f" ] || { echo "Cannot read: \$f" >&2; unreadable=\$((unreadable + 1)); }
    done < file_list.txt
    if [ "\$unreadable" -gt 0 ]; then
        echo "\$unreadable input file(s) are not readable (container mounts? permissions?)" >&2
        exit 2
    fi

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

    check_chunk.py \\
        --outdir "${chunk_id}" \\
        --log "log_${chunk_id}.txt" \\
        --patch-report "${patch_report}" \\
        --expected-sets ${expected} \\
        --input-dir "\$PWD/input" \\
        --features-dir "features_${chunk_id}" \\
        --manifest "features_${chunk_id}/mask_manifest.csv" \\
        --qc "qc_${chunk_id}.json" ${strict} ${requiredMetadata}
    """

    stub:
    """
    mkdir -p "${chunk_id}/masks/stub" "features_${chunk_id}"
    printf 'ImageNumber,Count_Nuclei,FileName_DNA,PathName_DNA\\n1,10,image_1.tif,stub\\n2,12,image_2.tif,stub\\n' > "features_${chunk_id}/MyExpt_Image.csv"
    printf 'ImageNumber,ObjectNumber,AreaShape_Area\\n1,1,100\\n2,1,90\\n' > "features_${chunk_id}/MyExpt_Nuclei.csv"
    printf 'ImageNumber,FileName_DNA,PathName_DNA,InputPath_DNA,MaskObject,MaskPath\\n1,image_1.tif,stub,stub/image_1.tif,Nuclei,masks/stub/${chunk_id}_image_1_Nuclei_mask.tiff\\n2,image_2.tif,stub,stub/image_2.tif,Nuclei,masks/stub/${chunk_id}_image_2_Nuclei_mask.tiff\\n' > "features_${chunk_id}/mask_manifest.csv"
    touch "${chunk_id}/masks/stub/${chunk_id}_image_1_Nuclei_mask.tiff"
    touch "${chunk_id}/masks/stub/${chunk_id}_image_2_Nuclei_mask.tiff" "log_${chunk_id}.txt"
    echo '{}' > "qc_${chunk_id}.json"
    """
}

process MERGE_FEATURES {
    label 'merge'
    publishDir "${params.outdir}/features", mode: params.publish_mode

    input:
    path chunk_dirs

    output:
    path '*.csv{,.gz}',        emit: tables
    path 'merge_report.json',  emit: report

    script:
    def unique = params.required_metadata ? "--unique-metadata '${params.required_metadata}'" : ''
    """
    merge_features.py --outdir . ${boolParam('gzip_features') ? '--gzip' : ''} ${unique} ${chunk_dirs}
    """
}

// ------------------------------------------------------------------ workflow
workflow {
    validateParams()

    def inputDir     = file(params.input_dir).toAbsolutePath().normalize()
    def exts         = imageExtensions()
    def chunkSize    = params.chunk_size as int
    def groupPattern = params.group_regex ? java.util.regex.Pattern.compile(params.group_regex.toString()) : null
    def plugins      = params.plugins_dir ? file(params.plugins_dir) : []
    def allowIncomplete = boolParam('allow_incomplete_sets')
    def onCluster    = workflow.profile.tokenize(',').any { p -> p in ['slurm', 'berzelius'] }

    log.info """\
        ==================================  cp-headless  ==================================
        pipeline     : ${params.pipeline}
        input_dir    : ${inputDir}
        outdir       : ${params.outdir}
        extensions   : ${exts.join(', ')}
        group_regex  : ${params.group_regex ?: '(none: every file is its own image set)'}
        chunk_size   : ${chunkSize ?: 'all image sets in one job'}
        save_masks   : ${boolParam('save_masks')} (${params.mask_format})
        container    : ${params.container}
        =================================================================================
        """.stripIndent()

    writeRunInfo()

    // 1. discover images (recursive, case-insensitive extension match, hidden files skipped)
    ch_images = channel
        .fromPath("${inputDir}/**", type: 'file')
        .filter { f ->
            def n = f.name.toLowerCase()
            exts.any { ext -> n.endsWith(".${ext}") }
        }
        .map { f -> inputDir.relativize(f).toString() }
        .ifEmpty { cpnfError("no files with extensions [${exts.join(', ')}] found under ${inputDir}") }

    // 2. group files into image sets, then batch whole image sets into chunks
    ch_chunks = ch_images
        .map { rel ->
            def key = "__single__/${rel}"
            if (groupPattern) {
                def m = groupPattern.matcher(rel)
                if (m.find()) {
                    key = m.groupCount() > 0
                        ? (1..m.groupCount()).collect { i -> m.group(i) ?: '' }.join('|')
                        : m.group(0)
                } else {
                    key = "__unmatched__/${rel}"
                }
            }
            tuple(key, rel)
        }
        .groupTuple(sort: true)
        .toSortedList { a, b -> a[0] <=> b[0] }
        .flatMap { groups ->
            // Image-set integrity: every file must match group_regex, and every image set must
            // have the same number of files (one per channel). The most common size is taken
            // as the channel count; other sizes mean a missing channel or extra files.
            def unmatched  = groups.findAll { g -> g[0].startsWith('__unmatched__/') }
            def matched    = groups.findAll { g -> !g[0].startsWith('__unmatched__/') }
            def channels   = 0
            def incomplete = []
            if (groupPattern && matched) {
                channels   = matched.collect { g -> g[1].size() }.countBy { n -> n }.max { e -> e.value }.key
                incomplete = matched.findAll { g -> g[1].size() != channels }
                log.info "[cp-headless] image sets have ${channels} file(s) each (most common size)"
            }
            def problems = []
            if (unmatched)
                problems << "${unmatched.size()} file(s) do not match --group_regex, e.g. ${unmatched.take(3).collect { g -> g[1][0] }}"
            if (incomplete)
                problems << "${incomplete.size()} image set(s) do not have ${channels} file(s), e.g. " +
                    incomplete.take(3).collect { g -> "${g[0]} -> ${g[1]}" }.join('; ')
            if (problems && allowIncomplete) {
                log.warn "[cp-headless] ${problems.join('\n')}\n" +
                    "Continuing because --allow_incomplete_sets is true: unmatched files become their own image sets."
            } else if (problems) {
                cpnfError("${problems.join('\n')}\n" +
                    "Fix --group_regex or --extensions, or remove the files. " +
                    "Set --allow_incomplete_sets true to process them anyway.")
            }
            def batches = chunkSize > 0 ? groups.collate(chunkSize) : [groups]
            if (onCluster && chunkSize == 0 && groups.size() > 500)
                log.warn "[cp-headless] ${groups.size()} image sets run as ONE cluster job (--chunk_size 0). " +
                    "Set --chunk_size so that one job takes 15-60 min: one job can not run longer than the wall-time limit."
            def width   = Math.max(4, batches.size().toString().length())
            log.info "[cp-headless] ${groups.size()} image set(s), ${groups.sum { g -> g[1].size() }} file(s) -> ${batches.size()} chunk(s)"
            batches.indexed().collect { i, batch ->
                tuple("chunk_${(i + 1).toString().padLeft(width, '0')}", batch.collectMany { g -> g[1] }, batch.size())
            }
        }

    // 3. patch the pipeline once, run every chunk, merge the tables
    PATCH_PIPELINE(file(params.pipeline), plugins)
    CELLPROFILER(ch_chunks, PATCH_PIPELINE.out.pipeline, PATCH_PIPELINE.out.report, inputDir, plugins)
    MERGE_FEATURES(CELLPROFILER.out.features.collect())

    // 4. cross-chunk sanity check: two chunks writing the same mask path would overwrite on publish
    CELLPROFILER.out.masks
        .flatMap { chunk_id, files ->
            (files instanceof List ? files : [files]).collect { f ->
                def s = f.toString()
                def marker = "/${chunk_id}/masks/"
                s.substring(s.indexOf(marker) + marker.length())
            }
        }
        .toList()
        .subscribe { paths ->
            def dups = paths.countBy { p -> p }.findAll { e -> e.value > 1 }
            if (dups)
                log.warn "[cp-headless] ${dups.size()} mask path collision(s) detected, e.g. ${dups.keySet().take(3)}; MERGE_FEATURES will fail the run."
        }
}
