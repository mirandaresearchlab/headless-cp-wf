"""Check the completed six-image-set smoke run and save a summary."""
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent
result = root / 'results/projects/smoke'
status = json.loads(sorted((result / 'logs').glob('status-*.json'))[-1].read_text())
assert status['success'] is True, status
plan = json.loads((result / 'logs/run_inputs/plan.json').read_text())
assert len(plan) == 3 and sum(p['sets'] for p in plan) == 6
expected_batches = sum(len(p['batches']) for p in plan)
validations = [json.loads(p.read_text()) for p in (result / 'logs').glob('*/batch_*.validation.json')]
assert len(validations) == expected_batches == 6
assert sum(v['image_sets'] for v in validations) == 6
mask_count = len(list((result / 'masks').glob('*/*.tiff')))
assert mask_count == sum(v['masks'] for v in validations) == 30
assert len(list((result / 'illum').glob('*/*.npy'))) == 15
counts = Counter()
acquisitions = set()
seen = set()
with gzip.open(result / 'cp_features/all_plates.csv.gz', 'rt') as stream:
    reader = csv.DictReader(stream)
    columns = len(reader.fieldnames)
    for row in reader:
        key = (row['Metadata_Plate'], row['Metadata_Acquisition'], row['Metadata_ObjectNumber'])
        assert key not in seen, key
        seen.add(key)
        counts[key[0]] += 1
        acquisitions.add(key[:2])
for plate in plan:
    report = json.loads((result / 'logs' / plate['plate'] / 'merge.json').read_text())
    assert report['cells'] == counts[plate['plate']] > 0
    assert report['columns'] == columns
with (root / 'launch/trace.txt').open() as stream:
    tasks = list(csv.DictReader(stream, delimiter='\t'))
assert len(tasks) == 14 and all(t['status'] == 'COMPLETED' and t['exit'] == '0' for t in tasks)
summary = dict(success=True, duration=status['duration'], tasks=len(tasks), image_sets=6,
               masks=mask_count, cells=sum(counts.values()), cells_per_plate=dict(counts),
               image_sets_with_cells=len(acquisitions), columns=columns,
               session_id=status['session_id'])
(root / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary, indent=2))
