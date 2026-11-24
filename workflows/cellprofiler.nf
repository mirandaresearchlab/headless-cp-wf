/*
 * The CellProfiler workflow: from a samplesheet to one per-cell feature table per plate.
 *
 *   1. PREPARE reads the samplesheet once. It groups the files into image sets, plans the
 *      batches, and writes the LoadData manifests and the working copies of the pipelines.
 *   2. ILLUMINATION runs once per plate and writes one correction function per channel.
 *   3. SEGMENT runs only if 2_analysis.cppipe has RunCellpose (Cellpose-SAM): once per group of
 *      --segmentation_batches batches, on a GPU or a CPU (--segmentation). It saves the masks.
 *   4. ANALYSIS runs once per batch: correct, segment (or load the SEGMENT masks), measure, save
 *      masks, export tables. It always runs on CPUs.
 *   5. MERGE runs once per plate. It joins the batch tables into one row per cell and writes
 *      <plate>.parquet. The plate files have the same columns and types, so they read as one table.
 *
 * With --segmentation_only, the run stops after SEGMENT. SEGMENT publishes its masks, and
 * ANALYSIS and MERGE do not run.
 *
 * Terms:
 *   image set  all channel files of one acquisition position (plate, well, site)
 *   batch      a fixed group of complete image sets from one plate
 *   manifest   a CSV file that lists the files of each image set (CellProfiler LoadData format)
 *   contract   contract.json: facts that PREPARE read from the pipelines (channels, objects,
 *              illumination functions, cell compartments). Later steps check against it.
 */

include { PREPARE } from '../modules/local/prepare'
include { ILLUMINATION } from '../modules/local/illumination'
include { SEGMENT } from '../modules/local/segment'
include { ANALYSIS } from '../modules/local/analysis'
include { MERGE } from '../modules/local/merge'

workflow CELLPROFILER {
    take:
    destination // String: the output folder of this run
    samplesheet // Path: the samplesheet CSV file
    configs // List of Path: 1_illumination.cppipe and 2_analysis.cppipe
    code // List of Path: the helper scripts in bin/
    plugins // List of Path: the CellProfiler plugins in plugins/

    main:
    // PREPARE gets every image file of the samplesheet as one sorted list. Nextflow tracks each
    // file, so a changed image runs the tasks that use it again on -resume.
    PREPARE(destination, samplesheetImages(samplesheet), samplesheet, configs, code, plugins)
    prepared = PREPARE.out
    // Batches per SEGMENT task. 0: 16 on a GPU, 1 on CPUs (see nextflow.config).
    def groupSize = (params.segmentation_batches as Integer) ?: (params.segmentation == 'gpu' ? 16 : 1)
    plan = prepared.map { dir -> readPlan(dir, groupSize) }
    contract = prepared.map { dir -> dir.resolve('pipelines/contract.json') }

    // One item per plate: (plate, plate manifest, all images of the plate).
    plates = plan.flatMap { items -> items.collect { p -> tuple(p.plate, p.manifest, p.images) } }

    // One item per batch: (plate, batch, batch manifest, batch images, true if SEGMENT makes its masks).
    batches = plan.flatMap { items -> items.collectMany { p -> p.batches.collect { b -> tuple(p.plate, b.batch, b.manifest, b.images, p.groups as Boolean) } } }

    // One item per SEGMENT task: (plate, group, batch manifests, their images). None without RunCellpose.
    groups = plan.flatMap { items -> items.collectMany { p -> p.groups.collect { g -> tuple(p.plate, g.group, g.manifests, g.images) } } }

    ILLUMINATION(destination, plates, prepared.map { dir -> dir.resolve('pipelines/illumination.cppipe') }, contract, code, plugins)

    // Like the batches, each group gets the .npy folder of its own plate.
    SEGMENT(
        destination,
        groups.combine(ILLUMINATION.out.functions, by: 0),
        prepared.map { dir -> dir.resolve('pipelines/segmentation.cppipe') },
        contract,
        code,
        plugins,
    )

    // One item per segmented batch: ((plate, batch), its SEGMENT folder). The folder name is the batch.
    masks = SEGMENT.out.batches.flatMap { plate, dirs -> (dirs instanceof List ? dirs : [dirs]).collect { dir -> tuple(tuple(plate, dir.name), dir) } }

    // --segmentation_only: SEGMENT publishes the masks, and the run ends there.
    table = channel.empty()
    // Command-line values are text, so compare as text: 'false' must mean false.
    if (params.segmentation_only.toString() != 'true') {
        // combine(by: 0) pairs each batch with the .npy folder of its own plate.
        // The batches of a plate start as soon as the illumination of that plate is complete.
        // With RunCellpose, join() also pairs each batch with its own SEGMENT folder, by plate and batch.
        // It stops the run if a batch has no SEGMENT folder or two of them.
        ready = batches
            .combine(ILLUMINATION.out.functions, by: 0)
            .branch { item ->
                segmented: item[4]
                plain: true
            }
        segmented = ready.segmented
            .map { plate, batch, manifest, images, _segmented, functions -> tuple(tuple(plate, batch), plate, batch, manifest, images, functions) }
            .join(masks, failOnMismatch: true, failOnDuplicate: true)
            .map { _key, plate, batch, manifest, images, functions, folder -> tuple(plate, batch, manifest, images, functions, folder) }
        ANALYSIS(
            destination,
            ready.plain.map { plate, batch, manifest, images, _segmented, functions -> tuple(plate, batch, manifest, images, functions, []) }.mix(segmented),
            prepared.map { dir -> dir.resolve('pipelines/analysis.cppipe') },
            contract,
            code,
            plugins,
        )

        // MERGE gets (plate, plate manifest) joined with (plate, all batch folders of the plate).
        MERGE(
            destination,
            plates.map { plate, manifest, _images -> tuple(plate, manifest) }.join(plateBatches(ANALYSIS.out.results, plan)),
            contract,
            code,
        )
        table = MERGE.out.table
    }

    emit:
    table = table
}

/*
 * The image files of a samplesheet, as one sorted list.
 *
 * A relative path starts from the folder of the samplesheet. PREPARE checks every row in full.
 * Here only the paths are needed, so that Nextflow can stage and track the files.
 */
def samplesheetImages(sheet) {
    return channel.fromPath(sheet)
        .splitCsv(header: true, strip: true)
        .map { row ->
            if (!row.path) {
                error("Samplesheet ${sheet.name}: every row needs a value in the column 'path'")
            }
            def image = sheet.parent.resolve(row.path.toString())
            if (!image.exists()) {
                error("Samplesheet ${sheet.name}: file not found: ${row.path}")
            }
            image
        }
        .unique()
        .toSortedList()
        .map { paths ->
            if (!paths) {
                error("Samplesheet ${sheet.name} has no rows")
            }
            paths
        }
}

/*
 * Read plan.json and contract.json from the PREPARE folder.
 *
 * Returns one map per plate: plate name, plate manifest, all images, its batches (batch name,
 * batch manifest, batch images), and its SEGMENT groups. A group is up to groupSize consecutive
 * batches of the plate (group name, batch manifests, images). Without RunCellpose in the
 * analysis pipeline (contract.segmentation is empty), there are no groups.
 */
def readPlan(dir, groupSize) {
    def segmented = new groovy.json.JsonSlurper().parse(dir.resolve('pipelines/contract.json').toFile()).segmentation as Boolean
    if (params.segmentation_only.toString() == 'true' && !segmented) {
        error('--segmentation_only needs RunCellpose in 2_analysis.cppipe: without it, segmentation is part of ANALYSIS')
    }
    return new groovy.json.JsonSlurper()
        .parse(dir.resolve('plan.json').toFile())
        .collect { p ->
            def batches = p.batches.collect { b -> [batch: b.batch, manifest: dir.resolve(b.manifest), images: b.images.collect { image -> file(image) }] }
            def chunks = segmented ? batches.collate(groupSize) : []
            [
                plate: p.plate,
                manifest: dir.resolve(p.manifest),
                images: p.images.collect { image -> file(image) },
                batches: batches,
                groups: (0..<chunks.size()).collect { i -> [group: String.format('segment_%04d', i + 1), manifests: chunks[i]*.manifest, images: chunks[i].collectMany { b -> b.images }] },
            ]
        }
}

/*
 * Collect the batch folders of each plate into one item for MERGE.
 *
 * results: one (plate, batch folder) item per finished ANALYSIS task.
 * plan:    the plan from readPlan(). It gives the number of batches per plate.
 * groupKey tells groupTuple how many batches to expect, so a plate goes to MERGE as soon as its
 * last batch arrives. One plate never waits for another. The sort keeps -resume stable.
 */
def plateBatches(results, plan) {
    def counts = plan.flatMap { items -> items.collect { p -> tuple(p.plate, p.batches.size()) } }
    return results
        .combine(counts, by: 0)
        .map { plate, dir, n -> tuple(groupKey(plate, n), dir) }
        .groupTuple()
        .map { key, dirs -> tuple(key.getGroupTarget(), dirs.sort { dir -> dir.name }) }
}
