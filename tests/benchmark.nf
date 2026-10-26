/*
 * Test driver: run the analysis again on a finished run, with the SAME illumination files.
 *
 * Use it to check that batching does not change results. Run it twice with different
 * --batch_size values, then compare the two runs with tests/compare_runs.py.
 *
 *   nextflow run tests/benchmark.nf --baseline <outdir>/projects/<run> --project one  --batch_size 6 --sets_per_plate 6
 *   nextflow run tests/benchmark.nf --baseline <outdir>/projects/<run> --project many --batch_size 2 --sets_per_plate 6
 *
 * In:  the baseline run's logs/run_inputs/ (plan and pipelines) and illum/<plate>/.
 * Out: <outdir>/projects/<project>/, the same layout as a normal run, plus test_manifests/.
 */
nextflow.enable.dsl = 2
include { ANALYSIS ; MERGE ; CONCAT ; plateBatches } from '../main.nf'

params.baseline = null

// 0 means all image sets. Any other number N means the first N image sets of each plate.
params.sets_per_plate = 0

workflow {
    if (!params.baseline || !params.project) {
        error('Supply --baseline and a fresh --project')
    }
    def baseline = file(params.baseline).toRealPath()
    def destination = file("${params.outdir}/projects/${params.project}").toAbsolutePath().normalize()
    if (destination.exists()) {
        error("Benchmark output already exists: ${destination}")
    }
    destination.mkdirs()

    // Read the plan of the baseline run and rebuild its batches with the new batch size.
    def source = baseline.resolve('logs/run_inputs')
    def plan = new groovy.json.JsonSlurper().parse(source.resolve('plan.json').toFile())
    def jobs = []
    def plates = []
    plan.each { plate ->
        def records = source.resolve(plate.manifest).text.readLines()
        def header = records.first()
        def all = records.drop(1)

        // The plan lists the images channel by channel. Group them into one list per image set.
        def images = plate.images.collate(plate.images.size().intdiv(all.size()))
        def limit = (params.sets_per_plate as int) ?: all.size()
        def rows = all.take(limit)
        images = images.take(limit)

        // MERGE checks against this plate manifest, so it must list only the chosen image sets.
        def subset = destination.resolve("test_manifests/${plate.plate}/plate.csv")
        subset.parent.mkdirs()
        subset.text = header + '\n' + rows.join('\n') + '\n'
        plates << tuple(plate.plate, subset)
        rows
            .collate(params.batch_size as int)
            .eachWithIndex { chunk, index ->
                def batch = String.format('batch_%04d', index + 1)
                def folder = destination.resolve("test_manifests/${plate.plate}")
                folder.mkdirs()
                def manifest = folder.resolve("${batch}.csv")

                // Generated metadata CSV contains no quoted commas. Change only the Batch field.
                def batchColumn = header.split(',').toList().indexOf('Metadata_Batch')
                manifest.text = header + '\n' + chunk.collect { line ->
                    def cells = line.split(',', -1).toList()
                    cells[batchColumn] = batch
                    cells.join(',')
                }.join('\n') + '\n'

                // Each batch uses the illumination files of its own plate from the baseline run.
                def selected = images.drop(index * (params.batch_size as int)).take(chunk.size()).flatten().collect { image -> file(image) }
                jobs << tuple(plate.plate, batch, manifest, selected, baseline.resolve("illum/${plate.plate}"))
            }
    }
    def code = file("${projectDir}/../bin/*.py")
    ANALYSIS(
        destination.toString(),
        channel.fromList(jobs),
        source.resolve('pipelines/analysis.cppipe'),
        source.resolve('pipelines/contract.json'),
        code,
        file("${projectDir}/../plugins/*.py"),
    )

    // Count batches per plate so the merge waits for the complete plate.
    def counts = jobs.countBy { job -> job[0] }
    def plateBatchPlan = channel.value(counts.collect { plate, n -> [plate: plate, batches: (1..n).toList()] })
    def contract = source.resolve('pipelines/contract.json')
    MERGE(destination.toString(), channel.fromList(plates).join(plateBatches(ANALYSIS.out.results, plateBatchPlan)), contract, code)
    CONCAT(destination.toString(), MERGE.out.table.toSortedList { a, b -> a.name <=> b.name }, code)
}
