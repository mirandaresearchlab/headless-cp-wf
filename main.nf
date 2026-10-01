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

def imageExtensions() {
    params.extensions.toString().tokenize(',')
        .collect { it.trim().toLowerCase().replaceFirst(/^\./, '') }
        .findAll { it }
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

    if (!params.chunk_size.toString().isInteger() || (params.chunk_size as int) < 0)
        cpnfError("--chunk_size must be an integer >= 0 (0 = all images in one CellProfiler job)")
    if (!(params.mask_format in ['tiff', 'png', 'npy']))
        cpnfError("--mask_format must be one of tiff, png, npy")
    if (!imageExtensions())
        cpnfError("--extensions is empty")
    if (params.plugins_dir && !file(params.plugins_dir).isDirectory())
        cpnfError("--plugins_dir is not a directory: ${params.plugins_dir}")
    if (params.group_regex) {
        try { java.util.regex.Pattern.compile(params.group_regex.toString()) }
        catch (Exception e) { cpnfError("invalid --group_regex: ${e.message}") }
    }
    if ((params.chunk_size as int) > 0 && !params.group_regex) {
        log.warn """\
            [cp-headless] --chunk_size > 0 without --group_regex: files are split into chunks one by one.
            That is only correct for SINGLE-channel pipelines. For multi-channel image sets set
            --group_regex so all channels of a site land in the same chunk (see README).""".stripIndent()
    }
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
    if (!params.save_masks)    args << '--no-masks'
    if (params.mask_objects)   args << "--objects '${params.mask_objects}'"
    if (params.allow_unpatched) args << '--allow-unpatched'
    if (plugins)               args << '--plugins-dir "$PWD/plugins"'
    """
    export HOME="\$PWD" MPLCONFIGDIR="\$PWD/.mpl"
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
    def expected  = params.group_regex ? n_sets : -1
    def strict    = params.strict_image_count ? '--strict' : ''
    """
    set -euo pipefail
    # CellProfiler/matplotlib write settings into \$HOME; containers often have none.
    export HOME="\$PWD" MPLCONFIGDIR="\$PWD/.mpl" TMPDIR="\$PWD/tmp"
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
        --qc "qc_${chunk_id}.json" ${strict}
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
    """
    merge_features.py --outdir . ${params.gzip_features ? '--gzip' : ''} ${chunk_dirs}
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

    log.info """\
        ==================================  cp-headless  ==================================
        pipeline     : ${params.pipeline}
        input_dir    : ${inputDir}
        outdir       : ${params.outdir}
        extensions   : ${exts.join(', ')}
        group_regex  : ${params.group_regex ?: '(none: every file is its own image set)'}
        chunk_size   : ${chunkSize ?: 'all image sets in one job'}
        save_masks   : ${params.save_masks} (${params.mask_format})
        container    : ${params.container}
        =================================================================================
        """.stripIndent()

    // 1. discover images (recursive, case-insensitive extension match, hidden files skipped)
    ch_images = Channel
        .fromPath("${inputDir}/**", type: 'file')
        .filter { f ->
            def n = f.name.toLowerCase()
            exts.any { n.endsWith(".${it}") }
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
            def unmatched = groups.count { it[0].startsWith('__unmatched__/') }
            if (unmatched)
                log.warn "[cp-headless] ${unmatched} file(s) did not match --group_regex; each is treated as its own image set."
            def batches = chunkSize > 0 ? groups.collate(chunkSize) : [groups]
            def width   = Math.max(4, batches.size().toString().length())
            log.info "[cp-headless] ${groups.size()} image set(s), ${groups.sum { it[1].size() }} file(s) -> ${batches.size()} chunk(s)"
            batches.indexed().collect { i, batch ->
                tuple("chunk_${(i + 1).toString().padLeft(width, '0')}", batch.collectMany { it[1] }, batch.size())
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
            def dups = paths.countBy { it }.findAll { it.value > 1 }
            if (dups)
                log.warn "[cp-headless] ${dups.size()} mask path collision(s) detected, e.g. ${dups.keySet().take(3)}; MERGE_FEATURES will fail the run."
        }
}
