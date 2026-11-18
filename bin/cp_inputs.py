"""Read the naming rules from the two pipelines and check the image files against them.

The pipelines already say how CellProfiler reads a filename. The Metadata module has a regex.
The NamesAndTypes module says which channel gets which image name. This module reads those
rules, so the workflow groups the files in exactly the same way as CellProfiler would.

Data in:  the folder with the two .cppipe files, and either the list of TIFF paths (folder input)
          or a samplesheet CSV (--input). See read_samplesheet() for the samplesheet format.
Data out: a config dict with the naming rules, and a list of image sets.
          One image set is all channel files of one position (well, site, X/Y).

Run as a script, it writes the samplesheet for a folder of images:
    python bin/cp_inputs.py --images <images> --configs cp-configs --out samplesheet.csv
"""
import ast
import csv
import re
from collections import defaultdict
from pathlib import Path

import tifffile


def blocks(path):
    """Split a .cppipe file into one block of text per module.

    Args:
        path: the .cppipe file.

    Returns:
        A list of strings. Each string starts with the module name, e.g. "Metadata:[...".
    """

    # A module starts on a line like "Metadata:[module_num:2|...". The block runs to the next one.
    return re.findall(r'^\w+:\[.*?(?=^\w+:\[|\Z)', Path(path).read_text(), re.M | re.S)


def setting(block, key):
    """Return the value of one setting in a module block.

    Args:
        block: the text of one module, from blocks().
        key: the setting name as CellProfiler writes it, e.g. "Metadata source".

    Returns:
        The text after the colon.

    Raises:
        ValueError: if the setting is missing or appears more than once.
    """

    # Settings are indented by 4 spaces: "    <key>:<value>".
    values = re.findall(r'^    ' + re.escape(key) + r':(.*)$', block, re.M)
    if len(values) != 1:
        raise ValueError(f'Expected one {key!r}, found {values}')
    return values[0]


def read_config(folder):
    """Read the filename rules and the channel names from both pipelines.

    Both pipelines must use the same rules. The function stops on settings that this
    workflow cannot reproduce: spreadsheet metadata, 3D images, grouping, or Cellpose.

    Args:
        folder: the --configs folder with 1_illumination.cppipe and 2_analysis.cppipe.

    Returns:
        A dict with:
          regex          the filename regex, e.g. ^(?P<Well>...)_s(?P<Site>...)...
          channels       channel id in the filename -> CellProfiler image name, e.g. {"405": "DNA"}
          channel_field  the regex group that holds the channel, e.g. "Wavelength"
          keys           the metadata fields that CellProfiler uses to match channels

    Raises:
        ValueError: if a pipeline is missing, extra, or uses an unsupported setting.
    """
    folder = Path(folder)

    # Exactly these two pipelines, nothing more and nothing less.
    files = sorted(folder.glob('*.cppipe'))
    expected = {'1_illumination.cppipe', '2_analysis.cppipe'}
    if {p.name for p in files} != expected:
        raise ValueError(f'Configuration requires exactly {sorted(expected)}; found {[p.name for p in files]}')
    configs = []
    for path in files:
        modules = blocks(path)
        if any('cellpose' in b.splitlines()[0].lower() for b in modules):
            raise ValueError(f'{path}: Cellpose is not supported. Use watershed segmentation.')

        # Metadata module: one regex for the filename, and the plate from the folder name.
        metadata = next(b for b in modules if b.startswith('Metadata:'))
        regexes = []
        for part in metadata.split('    Metadata extraction method:')[1:]:
            if not part.startswith('Extract from file/folder names\n'):
                raise ValueError('Only regex metadata extraction is supported; no spreadsheets')
            source = setting(part, 'Metadata source')
            if source == 'File name':
                if setting(part, 'Extract metadata from') != 'All images':
                    raise ValueError('Filtered filename metadata extraction is unsupported')
                regexes.append(setting(part, 'Regular expression to extract from file name'))
            elif source == 'Folder name':
                if setting(part, 'Regular expression to extract from folder name') != r'(?P<Plate>[^\\/]+)$':
                    raise ValueError('Only the plate parent folder is supported for folder metadata')
            else:
                raise ValueError(f'Unsupported metadata source: {source}')
        if len(regexes) != 1:
            raise ValueError('Require exactly one filename metadata regex')

        # NamesAndTypes module: 2D images, and channels matched by metadata.
        names = next(b for b in modules if b.startswith('NamesAndTypes:'))
        if setting(names, 'Process as 3D?') != 'No':
            raise ValueError('Only single-plane 2D TIFF inputs are supported')
        if setting(names, 'Image set matching method') != 'Metadata':
            raise ValueError('NamesAndTypes must match image sets by metadata')

        # Each rule looks like: and (metadata does Wavelength "405"). It names one channel.
        channels = {}
        for assignment in names.split('    Select the rule criteria:')[1:]:
            rule = assignment.splitlines()[0]

            # Illumination functions are not raw images. LoadData adds them later.
            if setting(assignment, 'Select the image type') == 'Illumination function':
                continue
            match = re.fullmatch(r'and \(metadata does (\w+) "([^"]+)"\)', rule)
            if not match or setting(assignment, 'Select the image type') != 'Grayscale image':
                raise ValueError(f'Unsupported NamesAndTypes rule or type: {rule}')
            field, channel = match.groups()
            if channel in channels:
                raise ValueError(f'Duplicate configured channel: {channel}')
            channels[channel] = setting(assignment, 'Name to assign these images')
            if setting(assignment, 'Set intensity range from') != 'Image metadata':
                raise ValueError('Only image-metadata intensity scaling is supported')
        if not channels or len(set(channels.values())) != len(channels):
            raise ValueError('Channel names must be present and unique')

        # All channel rules must test the same metadata field, e.g. always Wavelength.
        fields = {re.fullmatch(r'and \(metadata does (\w+) "([^"]+)"\)', a.splitlines()[0])[1]
                  for a in names.split('    Select the rule criteria:')[1:]
                  if setting(a, 'Select the image type') != 'Illumination function'}
        if len(fields) != 1:
            raise ValueError('All channel rules must use the same metadata field')

        # The fields that CellProfiler compares to put channels together, e.g. Well and Site.
        matching = ast.literal_eval(setting(names, 'Match metadata'))
        keys = []
        for match in matching:
            values = {match.get(name) for name in channels.values()}
            if len(values) != 1 or None in values:
                raise ValueError('All channels must share the same acquisition matching keys')
            keys.append(values.pop())

        # Grouping changes how CellProfiler processes images, so batching would need a review.
        groups = next(b for b in modules if b.startswith('Groups:'))
        if setting(groups, 'Do you want to group your images?') != 'No':
            raise ValueError('Configured grouping requires a scientific review before batching; settings were not changed')
        configs.append(dict(regex=regexes[0], channels=channels, channel_field=fields.pop(), keys=keys))

    # Both pipelines must read the files the same way, or illumination and analysis would disagree.
    if configs[0] != configs[1]:
        raise ValueError('Illumination and analysis metadata/channel rules differ')
    return configs[0]


def validate_images(paths, config):
    """Group the TIFF files into image sets and check every file.

    The plate name comes from the parent folder. The other metadata comes from the filename
    regex. Files with the same metadata, apart from the channel, belong to one image set.

    Args:
        paths: all TIFF paths of the run.
        config: the naming rules from read_config().

    Returns:
        A list of image sets, sorted by metadata. Each image set is a dict with:
          metadata  e.g. {"Plate": "plate1", "Well": "A02", "Site": "1", ...}
          images    channel id -> file path, e.g. {"405": "/data/.../A02_s1_..._405_nm_Ex.tiff"}
          name      the part of the filename that all channels share, e.g. "A02_s1_x0_y0"

    Raises:
        ValueError: on a filename that does not match, an unknown, missing or duplicated
            channel, an ambiguous image set, a TIFF with more than one plane, or images of
            different sizes in one plate.
    """
    pattern = re.compile(config['regex'])
    sets = {}
    matches = {}
    shapes = defaultdict(set)
    for source in sorted(paths):

        # Nextflow gives links to the files. Follow them to get the real plate folder.
        path = Path(source).resolve()
        plate = path.parent.name
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', plate) or plate in {'logs', 'pipelines', 'manifests'}:
            raise ValueError(f'Unsafe or reserved plate name: {plate}')

        # Read the metadata from the filename with the pipeline's own regex.
        match = pattern.fullmatch(path.name)
        if not match:
            raise ValueError(f'unmatched filename: {path}')
        metadata = match.groupdict()
        if any(value is None for value in metadata.values()):
            raise ValueError(f'Missing metadata in {path}')

        # The image name is the filename up to the last metadata field that is not the channel,
        # e.g. A02_s1_x0_y0. Masks and the per-cell table use it to name the image set.
        fields = [g for g in metadata if g != config['channel_field']]
        name = path.name[:max(match.end(g) for g in fields)] if fields else ''

        # Take the channel out of the metadata. What is left identifies the image set.
        channel = metadata.pop(config['channel_field'])
        if channel not in config['channels']:
            raise ValueError(f'unknown channel {channel}: {path}')
        if 'Plate' in metadata and metadata['Plate'] != plate:
            raise ValueError(f'Filename plate differs from parent folder: {path}')
        metadata['Plate'] = plate
        key = tuple(sorted(metadata.items()))

        # CellProfiler matches channels only on its own keys. Two image sets must not look the same to it.
        cp_key = (plate,) + tuple(metadata[k] for k in config['keys'])
        if cp_key in matches and matches[cp_key] != key:
            raise ValueError(f'ambiguous image set for CellProfiler keys {config["keys"]}: {path}')
        matches[cp_key] = key

        # Add this file to its image set. Each channel may appear only once.
        row = sets.setdefault(key, dict(metadata=metadata, images={}, name=name))
        if row['name'] != name:
            raise ValueError(f'Channel files of one image set give different image names: {row["name"]} and {name} ({path})')
        if channel in row['images']:
            raise ValueError(f'duplicate channel {channel} for {metadata}: {row["images"][channel]} and {path}')

        shapes[plate].add(tiff_shape(path))
        row['images'][channel] = str(path)
    return finish(sets, shapes, config)


def tiff_shape(path):
    """Read only the TIFF header and return the image shape.

    Raises:
        ValueError: if the file is not one 2D plane of 8- or 16-bit unsigned integers.
    """
    with tifffile.TiffFile(path) as tiff:
        series = tiff.series[0]
        if len(tiff.series) != 1 or len(tiff.pages) != 1 or series.axes != 'YX' or len(series.shape) != 2:
            raise ValueError(f'Expected single-plane grayscale TIFF: {path}, axes={series.axes}, shape={series.shape}')
        if series.dtype.kind != 'u' or series.dtype.itemsize not in (1, 2):
            raise ValueError(f'Unsupported TIFF dtype {series.dtype}: {path}')
        return series.shape


def finish(sets, shapes, config):
    """The checks after all files are grouped, shared by the folder and the samplesheet input.

    Args:
        sets: {image set key: image set}, as built by validate_images or read_samplesheet.
        shapes: {plate: set of image shapes}.
        config: the naming rules from read_config().

    Returns:
        The image sets, sorted by their key.
    """
    if not sets:
        raise ValueError('No TIFF image sets found')

    # Every image set needs every channel.
    for row in sets.values():
        missing = set(config['channels']) - set(row['images'])
        if missing:
            raise ValueError(f'missing channels {sorted(missing)} for {row["metadata"]}')

    # One plate's correction function must fit all its images, so all images need one size.
    if any(len(s) != 1 for s in shapes.values()):
        raise ValueError(f'All images in a plate must share dimensions: {dict(shapes)}')
    return [sets[key] for key in sorted(sets)]


# ---------------------------------------------------------------------------------------------
# Samplesheet input
#
# A samplesheet is a CSV file with one row per image file:
#   plate,well,site,channel,path
#   P1,A02,1,DNA,/data/P1/A02_s1_w1.tiff
# plate, well, site, channel and path are required. channel is the CellProfiler image name from
# NamesAndTypes (for example DNA). path is the TIFF file; a relative path is read from the folder
# of the samplesheet. Each other column is more metadata: column x becomes Metadata_X in the
# output. The optional column acquisition names the image set in mask files and in
# Metadata_Acquisition; without it, the name is <well>_s<site>.
# The rows with the same plate, well, site and other metadata form one image set.
# ---------------------------------------------------------------------------------------------

REQUIRED = ('plate', 'well', 'site', 'channel', 'path')

# Columns that the workflow writes itself. A samplesheet must not set them.
RESERVED = {'Batch', 'PlateImageNumber', 'ImageNumber', 'ObjectNumber'}


def metadata_name(column):
    """The CellProfiler metadata name of a samplesheet column: x -> X, well -> Well."""
    return column[:1].upper() + column[1:]


def column_name(metadata):
    """The samplesheet column of a metadata name: Well -> well, X -> x."""
    return metadata[:1].lower() + metadata[1:]


def read_samplesheet(sheet, config):
    """Read a samplesheet, check every row and file, and group the files into image sets.

    The result has the same form as validate_images(), so the rest of PREPARE does not know
    which input the run used.

    Args:
        sheet: the samplesheet CSV file.
        config: the naming rules from read_config(). Only the channel names and the CellProfiler
            matching keys are used. The filename regex is not used.

    Returns:
        A list of image sets, sorted by metadata, as validate_images() returns.

    Raises:
        ValueError: on a missing or unknown column, an empty value, an unknown channel, a missing
            or unreadable file, a file listed twice, a channel listed twice for one image set,
            an image set with a missing channel, or images of different sizes in one plate.
    """
    sheet = Path(sheet).resolve()
    names = {name: channel for channel, name in config['channels'].items()}

    # utf-8-sig removes the byte-order mark that Excel writes at the start of a CSV file.
    with sheet.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.reader(stream)
        header = [c.strip() for c in next(reader, [])]
        rows = [[v.strip() for v in row] for row in reader if any(v.strip() for v in row)]

    # Check the columns once, before any row.
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ValueError(f'Samplesheet {sheet.name} is missing the columns {missing}. '
                         f'Required: {", ".join(REQUIRED)}')
    if len(set(header)) != len(header):
        raise ValueError(f'Samplesheet {sheet.name} has a column name twice: {header}')
    extra = [c for c in header if c not in REQUIRED and c != 'acquisition']
    for column in extra:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', column):
            raise ValueError(f'Samplesheet column {column!r} must start with a letter and use only letters, digits and _')
        if metadata_name(column) in RESERVED or metadata_name(column) in {'Plate', 'Well', 'Site', 'Acquisition'}:
            raise ValueError(f'Samplesheet column {column!r} is reserved')
    metadata_columns = ['plate', 'well', 'site'] + extra
    if len({metadata_name(c) for c in metadata_columns}) != len(metadata_columns):
        raise ValueError(f'Two samplesheet columns differ only in the case of the first letter: {metadata_columns}')

    # CellProfiler puts channels together by these keys, so the sheet must have them.
    absent = [k for k in config['keys'] if metadata_name(k) not in {metadata_name(c) for c in metadata_columns}]
    if absent:
        raise ValueError(f'The pipelines match channels on {config["keys"]}; the samplesheet needs the columns '
                         f'{[column_name(k) for k in absent]}')

    sets, matches, shapes, files = {}, {}, defaultdict(set), {}
    for line, values in enumerate(rows, 2):
        if len(values) != len(header):
            raise ValueError(f'Samplesheet line {line}: {len(values)} values, but {len(header)} columns')
        row = dict(zip(header, values))
        empty = [c for c in REQUIRED + tuple(extra) if not row[c]]
        if empty:
            raise ValueError(f'Samplesheet line {line}: empty value in {empty}')

        plate = row['plate']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', plate) or plate in {'logs', 'pipelines', 'manifests'}:
            raise ValueError(f'Samplesheet line {line}: unsafe or reserved plate name: {plate}')
        if row['channel'] not in names:
            raise ValueError(f'Samplesheet line {line}: unknown channel {row["channel"]!r}. '
                             f'The pipelines use: {", ".join(names)}')

        # A relative path is read from the folder of the samplesheet.
        path = Path(row['path'])
        path = (path if path.is_absolute() else sheet.parent / path).resolve()
        if not path.is_file():
            raise ValueError(f'Samplesheet line {line}: file not found: {row["path"]}')
        if path.suffix.lower() not in {'.tif', '.tiff'}:
            raise ValueError(f'Samplesheet line {line}: not a .tif or .tiff file: {row["path"]}')
        if path in files:
            raise ValueError(f'Samplesheet line {line}: the file is already on line {files[path]}: {path}')
        files[path] = line

        # The metadata of the image set, with the same names as filename metadata would have.
        metadata = {metadata_name(c): row[c] for c in metadata_columns}
        key = tuple(sorted(metadata.items()))
        cp_key = (plate,) + tuple(metadata[metadata_name(k)] for k in config['keys'])
        if cp_key in matches and matches[cp_key] != key:
            raise ValueError(f'Samplesheet line {line}: ambiguous image set for CellProfiler keys {config["keys"]}: '
                             f'two image sets share {cp_key} but differ in other metadata')
        matches[cp_key] = key

        name = row.get('acquisition') or f'{row["well"]}_s{row["site"]}'
        image_set = sets.setdefault(key, dict(metadata=metadata, images={}, name=name))
        if image_set['name'] != name:
            raise ValueError(f'Samplesheet line {line}: the files of one image set give different acquisition names: '
                             f'{image_set["name"]} and {name}')
        channel = names[row['channel']]
        if channel in image_set['images']:
            raise ValueError(f'Samplesheet line {line}: duplicate channel {row["channel"]} for {metadata}')
        shapes[plate].add(tiff_shape(path))
        image_set['images'][channel] = str(path)
    return finish(sets, shapes, config)


def samplesheet_rows(image_sets, config):
    """The samplesheet of a run: one row per file, in image set order, channels in pipeline order.

    Reading these rows back with read_samplesheet() gives the same image sets.

    Args:
        image_sets: the result of validate_images() or read_samplesheet().
        config: the naming rules from read_config().

    Returns:
        (columns, rows): the column names and a list of dicts.
    """
    first = ['Plate', 'Well', 'Site']
    others = sorted({k for s in image_sets for k in s['metadata']} - set(first))
    columns = [column_name(k) for k in first + others] + ['acquisition', 'channel', 'path']
    rows = []
    for image_set in image_sets:
        for channel, name in config['channels'].items():
            row = {column_name(k): v for k, v in image_set['metadata'].items()}
            row.update(acquisition=image_set['name'], channel=name, path=image_set['images'][channel])
            rows.append(row)
    return columns, rows


def write_samplesheet(path, image_sets, config):
    """Write the samplesheet of a run to a CSV file."""
    columns, rows = samplesheet_rows(image_sets, config)
    with Path(path).open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def find_images(folder):
    """Find the TIFF files of a folder run, as the workflow does: <folder>/<plate>/<file>.tif(f).

    Hidden files (names that start with a dot, such as macOS ._ files) are skipped.

    Raises:
        ValueError: if a TIFF file is not exactly one folder below <folder>.
    """
    folder = Path(folder)
    paths = []
    for path in sorted(folder.rglob('*')):
        relative = path.relative_to(folder)
        if any(part.startswith('.') for part in relative.parts) or not path.is_file():
            continue
        if path.suffix.lower() in {'.tif', '.tiff'}:
            if len(relative.parts) != 2:
                raise ValueError(f'Expected <images>/<plate>/<filename>.tiff: {path}')
            paths.append(path)
    if not paths:
        raise ValueError(f'No TIFF inputs found in {folder}')
    return paths


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='Write a samplesheet for a folder of images (<images>/<plate>/<file>.tiff). The plate '
                    'comes from the folder name, the other metadata from the filename regex of the pipelines. '
                    'Check the result, then run the workflow with --input <samplesheet>.')
    parser.add_argument('--images', type=Path, required=True, help='folder with one sub-folder per plate')
    parser.add_argument('--configs', type=Path, required=True, help='folder with the two .cppipe files')
    parser.add_argument('--out', type=Path, required=True, help='the samplesheet CSV file to write')
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise ValueError(f'{args.out} exists. Delete it or choose another --out.')
        config = read_config(args.configs)
        image_sets = validate_images(find_images(args.images), config)
        write_samplesheet(args.out, image_sets, config)
    except ValueError as error:
        parser.exit(2, f'Samplesheet not written: {error}\n')
    print(f'Wrote {args.out}: {len(image_sets)} image sets, {len(image_sets) * len(config["channels"])} files')
