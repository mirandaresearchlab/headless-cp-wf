"""Read the samplesheet and the pipeline rules, and check every image file.

This module is a library for ``prepare.py``, ``run_task.py`` and ``make_samplesheet.py``.

The pipelines say how CellProfiler names the channels: the NamesAndTypes module gives each
channel an image name (for example DNA). The samplesheet gives the plate, well, site, channel and
path of each image file. This module groups the files into image sets in the same way as
CellProfiler would, so the workflow and CellProfiler always agree on which files belong together.

Samplesheet format (one row per image file)::

    plate,well,site,channel,path
    P1,A02,1,DNA,/data/P1/A02_s1_w1.tiff

``plate``, ``well``, ``site``, ``channel`` and ``path`` are required. ``channel`` is the
CellProfiler image name. A relative ``path`` starts from the folder of the samplesheet. Each
other column is more metadata: column ``x`` becomes ``Metadata_X`` in the output. The optional
column ``acquisition`` names the image set in mask files and in ``Metadata_Acquisition``. Without
it, the name is ``<well>_s<site>``. Rows with the same plate, well, site and other metadata form
one image set.
"""

import ast
import csv
import re
from collections import defaultdict
from pathlib import Path

import tifffile

# A plate name becomes a folder name, so it must be safe, and it must not hide a workflow folder.
PLATE_NAME = r'[A-Za-z0-9][A-Za-z0-9_.-]*'
RESERVED_PLATES = {'logs', 'pipelines', 'manifests'}

REQUIRED = ('plate', 'well', 'site', 'channel', 'path')

# Metadata that the workflow writes itself. A samplesheet column must not set it.
RESERVED = {'Plate', 'Well', 'Site', 'Acquisition', 'Batch', 'PlateImageNumber', 'ImageNumber', 'ObjectNumber'}


# ---------------------------------------------------------------------------------------------
# CSV files
# ---------------------------------------------------------------------------------------------


def read_csv(path):
    """Read a CSV file as a list of dicts, one dict per row.

    Parameters
    ----------
    path : str or Path
        The CSV file.

    Returns
    -------
    list of dict
        One dict per row, keyed by the column names.
    """
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows, columns=None):
    """Write a list of dicts to a CSV file. Missing folders are created.

    Parameters
    ----------
    path : str or Path
        The CSV file to write.
    rows : list of dict
        The rows. Every dict must have the same keys.
    columns : list of str, optional
        The column order. Default: the keys of the first row, sorted by name.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or sorted(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------------------------
# Pipeline rules
# ---------------------------------------------------------------------------------------------


def blocks(path):
    """Split a .cppipe file into one block of text per module.

    Parameters
    ----------
    path : str or Path
        The .cppipe file.

    Returns
    -------
    list of str
        One string per module. Each string starts with the module name, e.g. ``"Metadata:[..."``.
    """
    # A module starts on a line like "Metadata:[module_num:2|...". The block runs to the next one.
    return re.findall(r'^\w+:\[.*?(?=^\w+:\[|\Z)', Path(path).read_text(), re.M | re.S)


def setting(block, key):
    """Return the value of one setting in a module block.

    Parameters
    ----------
    block : str
        The text of one module, from ``blocks()``.
    key : str
        The setting name as CellProfiler writes it, e.g. ``"Metadata source"``.

    Returns
    -------
    str
        The text after the colon.

    Raises
    ------
    ValueError
        If the setting is missing or appears more than once.
    """
    # Settings are indented by 4 spaces: "    <key>:<value>".
    values = re.findall(r'^    ' + re.escape(key) + r':(.*)$', block, re.M)
    if len(values) != 1:
        raise ValueError(f'Expected one {key!r}, found {values}')
    return values[0]


def read_config(folder):
    """Read the filename rule and the channel names from both pipelines.

    Both pipelines must use the same rules. The function stops on settings that this workflow
    cannot reproduce: spreadsheet metadata, 3D images or grouping.

    Parameters
    ----------
    folder : str or Path
        The folder with ``1_illumination.cppipe`` and ``2_analysis.cppipe``.

    Returns
    -------
    dict
        ``regex``: the filename regex, used only by ``make_samplesheet.py``.
        ``channels``: channel id in the filename -> CellProfiler image name, e.g. ``{"405": "DNA"}``.
        ``channel_field``: the regex group that holds the channel, e.g. ``"Wavelength"``.
        ``keys``: the metadata fields that CellProfiler uses to match channels, e.g. ``["Well", "Site"]``.

    Raises
    ------
    ValueError
        If a pipeline is missing or extra, or uses an unsupported setting.
    """
    folder = Path(folder)
    files = sorted(folder.glob('*.cppipe'))
    expected = {'1_illumination.cppipe', '2_analysis.cppipe'}
    if {p.name for p in files} != expected:
        raise ValueError(f'Configuration requires exactly {sorted(expected)}; found {[p.name for p in files]}')
    configs = []
    for path in files:
        modules = blocks(path)

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
        # Illumination functions are not raw images: LoadData adds them later, so skip them.
        channels, fields = {}, set()
        for assignment in names.split('    Select the rule criteria:')[1:]:
            kind = setting(assignment, 'Select the image type')
            if kind == 'Illumination function':
                continue
            match = re.fullmatch(r'and \(metadata does (\w+) "([^"]+)"\)', assignment.splitlines()[0])
            if not match or kind != 'Grayscale image':
                raise ValueError(f'Unsupported NamesAndTypes rule or type: {assignment.splitlines()[0]}')
            field, channel = match.groups()
            if channel in channels:
                raise ValueError(f'Duplicate configured channel: {channel}')
            if setting(assignment, 'Set intensity range from') != 'Image metadata':
                raise ValueError('Only image-metadata intensity scaling is supported')
            channels[channel] = setting(assignment, 'Name to assign these images')
            fields.add(field)
        if not channels or len(set(channels.values())) != len(channels):
            raise ValueError('Channel names must be present and unique')
        if len(fields) != 1:
            raise ValueError('All channel rules must use the same metadata field')

        # The fields that CellProfiler compares to put channels together, e.g. Well and Site.
        keys = []
        for match in ast.literal_eval(setting(names, 'Match metadata')):
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


# ---------------------------------------------------------------------------------------------
# Image files and image sets
# ---------------------------------------------------------------------------------------------


def tiff_shape(path):
    """Read only the TIFF header and return the image shape.

    Parameters
    ----------
    path : str or Path
        The TIFF file.

    Returns
    -------
    tuple of int
        The image shape (height, width).

    Raises
    ------
    ValueError
        If the file is not one 2D plane of 8- or 16-bit unsigned integers.
    """
    with tifffile.TiffFile(path) as tiff:
        series = tiff.series[0]
        if len(tiff.series) != 1 or len(tiff.pages) != 1 or series.axes != 'YX' or len(series.shape) != 2:
            raise ValueError(f'Expected single-plane grayscale TIFF: {path}, axes={series.axes}, shape={series.shape}')
        if series.dtype.kind != 'u' or series.dtype.itemsize not in (1, 2):
            raise ValueError(f'Unsupported TIFF dtype {series.dtype}: {path}')
        return series.shape


def check_image_sets(sets, shapes, config):
    """Run the checks that need all image sets, and sort them.

    Parameters
    ----------
    sets : dict
        Image set key -> image set (see ``read_samplesheet()``).
    shapes : dict
        Plate -> set of the image shapes in that plate.
    config : dict
        The rules from ``read_config()``.

    Returns
    -------
    list of dict
        The image sets, sorted by their key.

    Raises
    ------
    ValueError
        If there is no image set, an image set misses a channel, or the images of one plate
        have different sizes.
    """
    if not sets:
        raise ValueError('No TIFF image sets found')
    for image_set in sets.values():
        missing = set(config['channels']) - set(image_set['images'])
        if missing:
            raise ValueError(f'missing channels {sorted(missing)} for {image_set["metadata"]}')

    # One plate gets one correction function per channel, so all its images need one size.
    if any(len(s) != 1 for s in shapes.values()):
        raise ValueError(f'All images in a plate must share dimensions: {dict(shapes)}')
    return [sets[key] for key in sorted(sets)]


class ImageSets:
    """Collect image files into image sets, with the checks that apply to each file.

    Parameters
    ----------
    config : dict
        The rules from ``read_config()``.

    Notes
    -----
    An image set is keyed by all its metadata, sorted by name. CellProfiler matches channels
    only on ``config['keys']`` (e.g. Well and Site). So two image sets that differ only in other
    metadata would look like one image set to CellProfiler: ``add()`` stops on that.
    """

    def __init__(self, config):
        self.config = config
        self.sets, self.matches, self.shapes = {}, {}, defaultdict(set)

    def add(self, metadata, name, channel, path, where):
        """Add one image file to its image set.

        Parameters
        ----------
        metadata : dict
            The metadata of the image set, without the channel, e.g. ``{"Plate": "P1", "Well": "A02", "Site": "1"}``.
        name : str
            The name of the image set, e.g. ``"A02_s1"``.
        channel : str
            The channel id from the pipelines, e.g. ``"405"``.
        path : Path
            The image file.
        where : str
            The position of the file in the input, for error messages.

        Raises
        ------
        ValueError
            On an ambiguous image set, a second name for one image set, a duplicate channel,
            or a file that is not a single-plane 8- or 16-bit TIFF.
        """
        plate = metadata['Plate']
        key = tuple(sorted(metadata.items()))
        cp_key = (plate,) + tuple(metadata[k] for k in self.config['keys'])
        if self.matches.setdefault(cp_key, key) != key:
            raise ValueError(
                f'{where}: ambiguous image set for CellProfiler keys {self.config["keys"]}: '
                f'two image sets share {cp_key} but differ in other metadata'
            )
        image_set = self.sets.setdefault(key, dict(metadata=metadata, images={}, name=name))
        if image_set['name'] != name:
            raise ValueError(f'{where}: the files of one image set give different acquisition names: {image_set["name"]} and {name}')
        if channel in image_set['images']:
            raise ValueError(f'{where}: duplicate channel {self.config["channels"][channel]} for {metadata}')
        self.shapes[plate].add(tiff_shape(path))
        image_set['images'][channel] = str(path)

    def result(self):
        """Return the checked image sets, sorted by metadata.

        Returns
        -------
        list of dict
            The image sets (see ``check_image_sets()``).
        """
        return check_image_sets(self.sets, self.shapes, self.config)


# ---------------------------------------------------------------------------------------------
# Samplesheet
# ---------------------------------------------------------------------------------------------


def metadata_name(column):
    """Return the CellProfiler metadata name of a samplesheet column.

    Parameters
    ----------
    column : str
        The samplesheet column, e.g. ``well`` or ``x``.

    Returns
    -------
    str
        The metadata name with a capital first letter, e.g. ``Well`` or ``X``.
    """
    return column[:1].upper() + column[1:]


def column_name(metadata):
    """Return the samplesheet column of a metadata name.

    Parameters
    ----------
    metadata : str
        The metadata name, e.g. ``Well`` or ``X``.

    Returns
    -------
    str
        The column name with a small first letter, e.g. ``well`` or ``x``.
    """
    return metadata[:1].lower() + metadata[1:]


def check_header(header, sheet, config):
    """Check the column names of a samplesheet.

    Parameters
    ----------
    header : list of str
        The column names.
    sheet : Path
        The samplesheet, for error messages.
    config : dict
        The rules from ``read_config()``.

    Returns
    -------
    list of str
        The metadata columns: ``plate``, ``well``, ``site``, then the extra columns.

    Raises
    ------
    ValueError
        On a missing, repeated, unsafe or reserved column, or if a CellProfiler matching key
        has no column.
    """
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ValueError(f'Samplesheet {sheet.name} is missing the columns {missing}. Required: {", ".join(REQUIRED)}')
    if len(set(header)) != len(header):
        raise ValueError(f'Samplesheet {sheet.name} has a column name twice: {header}')
    extra = [c for c in header if c not in REQUIRED and c != 'acquisition']
    for column in extra:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', column):
            raise ValueError(f'Samplesheet column {column!r} must start with a letter and use only letters, digits and _')
        if metadata_name(column) in RESERVED:
            raise ValueError(f'Samplesheet column {column!r} is reserved')
    columns = ['plate', 'well', 'site'] + extra
    names = {metadata_name(c) for c in columns}
    if len(names) != len(columns):
        raise ValueError(f'Two samplesheet columns differ only in the case of the first letter: {columns}')
    absent = [k for k in config['keys'] if metadata_name(k) not in names]
    if absent:
        raise ValueError(
            f'The pipelines match channels on {config["keys"]}; the samplesheet needs the columns {[column_name(k) for k in absent]}'
        )
    return columns


def read_samplesheet(sheet, config):
    """Read a samplesheet, check every row and file, and group the files into image sets.

    Parameters
    ----------
    sheet : str or Path
        The samplesheet CSV file. See the module docstring for the format.
    config : dict
        The rules from ``read_config()``. Only the channel names and the matching keys are used.

    Returns
    -------
    list of dict
        One dict per image set, sorted by metadata:
        ``metadata`` (e.g. ``{"Plate": "P1", "Well": "A02", "Site": "1"}``),
        ``images`` (channel id -> real path of the file), and ``name`` (e.g. ``"A02_s1"``).

    Raises
    ------
    ValueError
        On a wrong column, an empty value, an unknown channel, a missing or unreadable file, a
        file listed twice, a channel listed twice for one image set, an image set with a missing
        channel, or images of different sizes in one plate. The message gives the line.
    """
    sheet = Path(sheet).resolve()
    channel_ids = {name: channel for channel, name in config['channels'].items()}

    # utf-8-sig removes the byte-order mark that Excel writes at the start of a CSV file.
    with sheet.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.reader(stream)
        header = [c.strip() for c in next(reader, [])]
        rows = [[v.strip() for v in row] for row in reader if any(v.strip() for v in row)]
    metadata_columns = check_header(header, sheet, config)

    image_sets, files = ImageSets(config), {}
    for line, values in enumerate(rows, 2):
        where = f'Samplesheet line {line}'
        if len(values) != len(header):
            raise ValueError(f'{where}: {len(values)} values, but {len(header)} columns')
        row = dict(zip(header, values))
        empty = [c for c in REQUIRED + tuple(metadata_columns) if not row[c]]
        if empty:
            raise ValueError(f'{where}: empty value in {sorted(set(empty), key=header.index)}')
        if not re.fullmatch(PLATE_NAME, row['plate']) or row['plate'] in RESERVED_PLATES:
            raise ValueError(f'{where}: unsafe or reserved plate name: {row["plate"]}')
        if row['channel'] not in channel_ids:
            raise ValueError(f'{where}: unknown channel {row["channel"]!r}. The pipelines use: {", ".join(channel_ids)}')

        # A relative path starts from the folder of the samplesheet.
        path = Path(row['path'])
        path = (path if path.is_absolute() else sheet.parent / path).resolve()
        if not path.is_file():
            raise ValueError(f'{where}: file not found: {row["path"]}')
        if path.suffix.lower() not in {'.tif', '.tiff'}:
            raise ValueError(f'{where}: not a .tif or .tiff file: {row["path"]}')
        if path in files:
            raise ValueError(f'{where}: the file is already on line {files[path]}: {path}')
        files[path] = line

        metadata = {metadata_name(c): row[c] for c in metadata_columns}
        name = row.get('acquisition') or f'{row["well"]}_s{row["site"]}'
        image_sets.add(metadata, name, channel_ids[row['channel']], path, where)
    return image_sets.result()


def write_samplesheet(path, image_sets, config):
    """Write the samplesheet of a run: one row per file, channels in pipeline order.

    Reading the file back with ``read_samplesheet()`` gives the same image sets.

    Parameters
    ----------
    path : str or Path
        The CSV file to write.
    image_sets : list of dict
        Image sets as ``read_samplesheet()`` returns them.
    config : dict
        The rules from ``read_config()``.
    """
    first = ['Plate', 'Well', 'Site']
    others = sorted({k for s in image_sets for k in s['metadata']} - set(first))
    columns = [column_name(k) for k in first + others] + ['acquisition', 'channel', 'path']
    rows = [
        dict({column_name(k): v for k, v in s['metadata'].items()}, acquisition=s['name'], channel=name, path=s['images'][channel])
        for s in image_sets
        for channel, name in config['channels'].items()
    ]
    write_csv(path, rows, columns)
