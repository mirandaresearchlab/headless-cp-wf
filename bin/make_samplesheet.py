#!/usr/bin/env python3
"""Write a samplesheet for a folder of images, so that nobody has to write it by hand.

    python bin/make_samplesheet.py --images <images> --configs cp-configs --out samplesheet.csv

<images> has one folder per plate: <images>/<plate>/<file>.tiff. The plate name is the folder
name. The other metadata comes from the filename, read with the regex in the Metadata module of
the pipelines. Hidden files (names that start with a dot, such as macOS ._ files) are skipped.
Check the result, delete the rows that you do not want, then run the workflow with --input.
"""
import argparse
import re
from pathlib import Path

from cp_inputs import PLATE_NAME, RESERVED_PLATES, ImageSets, read_config, write_samplesheet


def find_images(folder):
    """Find the TIFF files of an image folder: ``<folder>/<plate>/<file>.tif(f)``.

    Parameters
    ----------
    folder : str or Path
        The folder with one sub-folder per plate.

    Returns
    -------
    list of Path
        The TIFF files, sorted. Hidden files and files in hidden folders are skipped.

    Raises
    ------
    ValueError
        If a TIFF file is not exactly one folder below ``folder``, or there is no TIFF file.
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


def images_from_filenames(paths, config):
    """Group TIFF files into image sets with the filename regex of the pipelines.

    Parameters
    ----------
    paths : list of Path
        The TIFF files, each in its plate folder.
    config : dict
        The rules from ``cp_inputs.read_config()``.

    Returns
    -------
    list of dict
        The image sets, as ``cp_inputs.read_samplesheet()`` returns them. The name of an image
        set is the part of the filename that all its channels share, e.g. ``A02_s1_x0_y0``.

    Raises
    ------
    ValueError
        On an unsafe plate name, a filename that the regex does not match, an unknown channel,
        or any check of ``cp_inputs.ImageSets``.
    """
    pattern = re.compile(config['regex'])
    image_sets = ImageSets(config)
    for source in sorted(paths):

        # Follow links to get the real plate folder.
        path = Path(source).resolve()
        plate = path.parent.name
        if not re.fullmatch(PLATE_NAME, plate) or plate in RESERVED_PLATES:
            raise ValueError(f'Unsafe or reserved plate name: {plate}')
        match = pattern.fullmatch(path.name)
        if not match:
            raise ValueError(f'unmatched filename: {path}')
        metadata = match.groupdict()
        if any(value is None for value in metadata.values()):
            raise ValueError(f'Missing metadata in {path}')

        # The image set name is the filename up to the end of the last metadata field that is
        # not the channel, e.g. A02_s1_x0_y0 from A02_s1_x0_y0_Fluorescence_405_nm_Ex.tiff.
        fields = [g for g in metadata if g != config['channel_field']]
        name = path.name[:max(match.end(g) for g in fields)] if fields else ''

        # Take the channel out of the metadata. What is left identifies the image set.
        channel = metadata.pop(config['channel_field'])
        if channel not in config['channels']:
            raise ValueError(f'unknown channel {channel}: {path}')
        if metadata.setdefault('Plate', plate) != plate:
            raise ValueError(f'Filename plate differs from parent folder: {path}')
        image_sets.add(metadata, name, channel, path, str(path))
    return image_sets.result()


def main():
    """Parse the arguments and write the samplesheet. Exit with code 2 and one line on an error."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--images', type=Path, required=True, help='folder with one sub-folder per plate')
    parser.add_argument('--configs', type=Path, required=True, help='folder with the two .cppipe files')
    parser.add_argument('--out', type=Path, required=True, help='the samplesheet CSV file to write')
    args = parser.parse_args()
    try:
        if args.out.exists():
            raise ValueError(f'{args.out} exists. Delete it or choose another --out.')
        config = read_config(args.configs)
        image_sets = images_from_filenames(find_images(args.images), config)
        write_samplesheet(args.out, image_sets, config)
    except ValueError as error:
        parser.exit(2, f'Samplesheet not written: {error}\n')
    print(f'Wrote {args.out}: {len(image_sets)} image sets, {len(image_sets) * len(config["channels"])} files')


if __name__ == '__main__':
    main()
