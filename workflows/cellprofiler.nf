/*
 * The CellProfiler workflow: from a samplesheet to one per-cell feature table.
 *
 *   1. PREPARE reads the samplesheet once. It groups the files into image sets, plans the
 *      batches, and writes the LoadData manifests and the working copies of the pipelines.
 *   2. ILLUMINATION runs once per plate and writes one correction function per channel.
 *   3. ANALYSIS runs once per batch: correct, segment, measure, save masks, export tables.
 *   4. MERGE runs once per plate. It joins the batch tables into one row per cell.
 *   5. CONCAT runs once. It appends all plate tables into one CSV file.
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
include { ANALYSIS } from '../modules/local/analysis'
include { MERGE } from '../modules/local/merge'
include { CONCAT } from '../modules/local/concat'

workflow CELLPROFILER {
    take:
    destination // String: the output folder of this run
    samplesheet // Path: the samplesheet CSV file
    configs     // List of Path: 1_illumination.cppipe and 2_analysis.cppipe
    code        // List of Path: the helper scripts in bin/
    plugins     // List of Path: the CellProfiler plugins in plugins/

    main:
    // PREPARE gets every image file of the samplesheet as one sorted list. Nextflow tracks each
    // file, so a changed image runs the tasks that use it again on -resume.
    PREPARE(destination, samplesheetImages(samplesheet), samplesheet, configs, code, plugins)
    prepared = PREPARE.out
    plan = prepared.map { dir -> readPlan(dir) }
    contract = prepared.map { dir -> dir.resolve('pipelines/contract.json') }

    // One item per plate: (plate, plate manifest, all images of the plate).
    plates = plan.flatMap { items -> items.collect { p -> tuple(p.plate, p.manifest, p.images) } }

    // One item per batch: (plate, batch, batch manifest, batch images).
    batches = plan.flatMap { items -> items.collectMany { p -> p.batches.collect { b -> tuple(p.plate, b.batch, b.manifest, b.images) } } }

    ILLUMINATION(destination, plates, prepared.map { dir -> dir.resolve('pipelines/illumination.cppipe') }, contract, code, plugins)

    // combine(by: 0) pairs each batch with the .npy folder of its own plate.
    // The batches of a plate start as soon as the illumination of that plate is complete.
    ANALYSIS(
        destination,
        batches.combine(ILLUMINATION.out.functions, by: 0),
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

    // toSortedList waits for every plate table. This is the only step that waits for all plates.
    CONCAT(destination, MERGE.out.table.toSortedList { a, b -> a.name <=> b.name }, code)

    emit:
    table = CONCAT.out.table
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
 * Read plan.json from the PREPARE folder.
 *
 * Returns one map per plate: plate name, plate manifest, all images, and its batches
 * (batch name, batch manifest, batch images). Manifest paths become paths inside the folder.
 */
def readPlan(dir) {
    return new groovy.json.JsonSlurper()
        .parse(dir.resolve('plan.json').toFile())
        .collect { p ->
            [
                plate: p.plate,
                manifest: dir.resolve(p.manifest),
                images: p.images.collect { image -> file(image) },
                batches: p.batches.collect { b -> [batch: b.batch, manifest: dir.resolve(b.manifest), images: b.images.collect { image -> file(image) }] },
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
