"""Unit tests for the samplesheet input (bin/cp_inputs.py, and the samplesheet part of bin/prepare.py).

A samplesheet has one row per image file: plate, well, site, channel, path, and optional metadata.
The tests prove two things:
  - A samplesheet gives the same image sets as the folder input. So the manifests, the batches
    and the merge after PREPARE do not depend on which input the run used.
  - Each kind of bad samplesheet stops the run with a message that names the line or column.

They use the real cp-configs pipelines and small synthetic TIFFs.
"""
import csv
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from cp_inputs import find_images, read_config, read_samplesheet, validate_images, write_samplesheet  # noqa: E402

CONFIGS = Path(__file__).resolve().parents[1] / 'cp-configs'
WAVELENGTHS = {'DNA': '405', 'RNA': '488', 'AGP': '561', 'Mito': '638', 'ER': '730'}


@pytest.fixture(scope='module')
def config():
    """The naming rules of the real pipelines."""
    return read_config(CONFIGS)


def tiff(path, shape=(16, 16)):
    """Write one small 16-bit TIFF and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(path, np.zeros(shape, dtype=np.uint16))
    return path


def folder_plate(root, plate='P1', sites=(('A02', 1, 0, 0), ('A02', 2, 1, 0), ('B03', 1, 0, 0))):
    """A folder input with real filenames: <root>/<plate>/A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff."""
    return [tiff(root / plate / f'{well}_s{site}_x{x}_y{y}_Fluorescence_{w}_nm_Ex.tiff')
            for well, site, x, y in sites for w in WAVELENGTHS.values()]


def write_sheet(path, rows, header=None):
    """Write a samplesheet CSV from a list of dicts."""
    header = header or list(rows[0])
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def free_names(root, plate='P1', wells=('A02',), sites=(1,)):
    """Files with names that no regex knows, and the minimal samplesheet rows for them.

    The paths in the rows are relative to root, where the samplesheet is written.
    """
    rows = []
    for well in wells:
        for site in sites:
            for channel in WAVELENGTHS:
                name = f'scan/{plate}/img_{well}_{site}_{channel.lower()}.tif'
                tiff(root / name)
                rows.append(dict(plate=plate, well=well, site=str(site), channel=channel, path=name))
    return rows


def test_samplesheet_gives_the_same_image_sets_as_the_folder(tmp_path, config):
    """Folder -> samplesheet -> image sets: the same metadata, files, names and order as the folder input."""
    paths = folder_plate(tmp_path / 'images') + folder_plate(tmp_path / 'images', 'P2')
    from_folder = validate_images(paths, config)
    sheet = tmp_path / 'samplesheet.csv'
    write_samplesheet(sheet, from_folder, config)
    assert read_samplesheet(sheet, config) == from_folder

    # The written sheet has one row per file, and the CellProfiler channel names.
    rows = list(csv.DictReader(sheet.open()))
    assert len(rows) == len(paths)
    assert rows[0] == dict(plate='P1', well='A02', site='1', column='02', row='A', x='0', y='0',
                           acquisition='A02_s1_x0_y0', channel='DNA', path=str(paths[0].resolve()))


def test_minimal_samplesheet_with_any_filenames(tmp_path, config):
    """Only the five required columns. The files have names that the regex does not match, and
    relative paths. The image set gets the metadata of the sheet and the name <well>_s<site>."""
    sheet = write_sheet(tmp_path / 'samplesheet.csv', free_names(tmp_path, wells=('A02', 'B03'), sites=(1, 2)))
    image_sets = read_samplesheet(sheet, config)
    assert len(image_sets) == 4
    first = image_sets[0]
    assert first['metadata'] == dict(Plate='P1', Well='A02', Site='1')
    assert first['name'] == 'A02_s1'

    # The files are keyed by the channel of the pipelines, as for the folder input.
    assert first['images'] == {w: str((tmp_path / f'scan/P1/img_A02_1_{c.lower()}.tif').resolve())
                               for c, w in WAVELENGTHS.items()}


def test_extra_columns_and_acquisition(tmp_path, config):
    """Each extra column becomes metadata with a capital first letter. acquisition sets the image set name."""
    rows = [dict(r, timepoint='24h', acquisition='A02_s1_t24') for r in free_names(tmp_path)]
    [image_set] = read_samplesheet(write_sheet(tmp_path / 's.csv', rows), config)
    assert image_set['metadata'] == dict(Plate='P1', Well='A02', Site='1', Timepoint='24h')
    assert image_set['name'] == 'A02_s1_t24'


def test_excel_style_file_is_read(tmp_path, config):
    """A byte-order mark, spaces around values, and empty lines do not change the result."""
    rows = free_names(tmp_path)
    lines = ['plate , well , site , channel , path'] + [
        f' {r["plate"]} , {r["well"]} , {r["site"]} , {r["channel"]} , {r["path"]} ' for r in rows] + ['', ',,,,']
    sheet = tmp_path / 's.csv'
    sheet.write_text('﻿' + '\n'.join(lines) + '\n', encoding='utf-8')
    [image_set] = read_samplesheet(sheet, config)
    assert image_set['metadata'] == dict(Plate='P1', Well='A02', Site='1')


@pytest.mark.parametrize('change, message', [
    (lambda rows: [{k: v for k, v in r.items() if k != 'site'} for r in rows], r"missing the columns \['site'\]"),
    (lambda rows: [dict(r, channel='Actin') if r['channel'] == 'ER' else r for r in rows], "unknown channel 'Actin'.*DNA"),
    (lambda rows: rows[:-1], r"missing channels \['730'\]"),
    (lambda rows: rows + [dict(rows[0], path=rows[1]['path'])], 'already on line'),
    (lambda rows: rows + [rows[0]], 'already on line'),
    (lambda rows: [dict(r, path='scan/P1/none.tif') if r['channel'] == 'RNA' else r for r in rows], 'line 3: file not found'),
    (lambda rows: [dict(r, well='') if r['channel'] == 'AGP' else r for r in rows], r"line 4: empty value in \['well'\]"),
    (lambda rows: [dict(r, plate='../x') for r in rows], 'unsafe or reserved plate name'),
    (lambda rows: [dict(r, batch='b1') for r in rows], "column 'batch' is reserved"),
    (lambda rows: [dict(r, Batch='b1') for r in rows], "column 'Batch' is reserved"),
    (lambda rows: [dict(r, x='1', X='1') for r in rows], 'differ only in the case'),
    (lambda rows: [dict(r, acquisition=f'n{i}') for i, r in enumerate(rows)], 'different acquisition names'),
], ids=['missing column', 'unknown channel', 'missing channel', 'file twice', 'row twice', 'missing file',
        'empty value', 'unsafe plate', 'reserved column', 'reserved capital', 'case clash', 'two names'])
def test_bad_samplesheet_stops_the_run(tmp_path, config, change, message):
    """Each kind of mistake stops the run before any CellProfiler task, and the message says where."""
    rows = change(free_names(tmp_path))
    header = list(dict.fromkeys(k for r in rows for k in r))
    with pytest.raises(ValueError, match=message):
        read_samplesheet(write_sheet(tmp_path / 's.csv', rows, header), config)


def test_duplicate_channel_for_one_image_set(tmp_path, config):
    """Two different files for the DNA channel of one image set stop the run."""
    rows = free_names(tmp_path)
    tiff(tmp_path / 'other.tif')
    with pytest.raises(ValueError, match='duplicate channel DNA'):
        read_samplesheet(write_sheet(tmp_path / 's.csv', rows + [dict(rows[0], path='other.tif')]), config)


def test_ambiguous_image_set(tmp_path, config):
    """Two image sets with the same well and site, which differ only in an extra column, stop the run.
    CellProfiler matches channels on well and site, so it would mix their files."""
    rows = free_names(tmp_path)
    other = [dict(r, path=r['path'].replace('img_', 'other_'), x='1') for r in rows]
    for r in other:
        tiff(tmp_path / r['path'])
    with pytest.raises(ValueError, match='ambiguous'):
        read_samplesheet(write_sheet(tmp_path / 's.csv', [dict(r, x='0') for r in rows] + other), config)


def test_images_of_different_sizes_in_one_plate(tmp_path, config):
    """One plate gets one illumination function, so all its images need one size."""
    rows = free_names(tmp_path, wells=('A02', 'B03'))
    tiff(tmp_path / rows[-1]['path'], shape=(32, 32))
    with pytest.raises(ValueError, match='share dimensions'):
        read_samplesheet(write_sheet(tmp_path / 's.csv', rows), config)


def test_multiplane_file_in_samplesheet(tmp_path, config):
    """A TIFF stack in a samplesheet stops the run, as in a folder run."""
    rows = free_names(tmp_path)
    tifffile.imwrite(tmp_path / rows[0]['path'], np.zeros((2, 16, 16), dtype=np.uint16), photometric='minisblack')
    with pytest.raises(ValueError, match='single-plane'):
        read_samplesheet(write_sheet(tmp_path / 's.csv', rows), config)


def test_prepare_stops_if_staged_files_differ_from_samplesheet(tmp_path):
    """PREPARE checks that Nextflow staged exactly the files of the samplesheet, so every file is tracked.
    The check runs before CellProfiler is loaded."""
    from prepare import prepare
    rows = free_names(tmp_path)
    sheet = write_sheet(tmp_path / 's.csv', rows)
    staged = [tmp_path / r['path'] for r in rows[:-1]] + [tiff(tmp_path / 'stray.tif')]
    with pytest.raises(ValueError, match='Staged files differ from the samplesheet: 1 extra, 1 missing'):
        prepare(CONFIGS, staged, 4, tmp_path / 'prepared', sheet)


def test_find_images_skips_hidden_files(tmp_path):
    """The samplesheet script finds the same files as the workflow: macOS ._ files and hidden folders are skipped."""
    paths = folder_plate(tmp_path / 'images')
    (tmp_path / 'images' / 'P1' / '._A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff').write_bytes(b'not a tiff')
    tiff(tmp_path / 'images' / '.trash' / 'x.tiff')
    (tmp_path / 'images' / 'P1' / 'notes.txt').write_text('ignored')
    assert find_images(tmp_path / 'images') == sorted(paths)

    # A TIFF directly in the image folder has no plate folder.
    tiff(tmp_path / 'images' / 'loose.tiff')
    with pytest.raises(ValueError, match='Expected <images>/<plate>'):
        find_images(tmp_path / 'images')
