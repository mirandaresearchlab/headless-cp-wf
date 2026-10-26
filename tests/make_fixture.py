#!/usr/bin/env python3
"""Make a small test image folder: 512x512 crops of two real sites per plate.

    python tests/make_fixture.py <images> <new folder>

For each plate it reads the five channel files of sites A02_s1 and A03_s1. It writes the top-left
512x512 pixels with the original values to <new folder>/<plate>/<same filename>.
<new folder>.json records the source path, SHA-256 and crop of each file.
It never changes the source images and stops if the new folder already exists.
"""
import argparse
import hashlib
import json
from pathlib import Path

import tifffile


def make_fixture(source, destination):
    """Write the crops and the JSON record.

    Args:
        source: the image folder with one subfolder per plate.
        destination: the new folder for the crops. It must not exist yet.

    Raises:
        ValueError: if the destination exists, or a plate does not have two complete
            five-channel sites.
    """

    # Never write into an existing folder.
    if destination.exists():
        raise ValueError(f'Fixture destination already exists: {destination}')
    records = []
    for plate in sorted(p for p in source.iterdir() if p.is_dir()):

        # The five channel files of site 1 in wells A02 and A03.
        paths = [p for p in sorted(plate.glob('*.tiff')) if p.name.startswith(('A02_s1_', 'A03_s1_'))]
        if len(paths) != 10:
            raise ValueError(f'Expected two complete five-channel sites in {plate}')
        for path in paths:
            data = tifffile.imread(path)

            # Same top-left field region and original intensity values in every channel.
            cropped = data[:512, :512]
            out = destination / plate.name / path.name
            out.parent.mkdir(parents=True, exist_ok=True)
            tifffile.imwrite(out, cropped, photometric='minisblack')

            # Record where each crop came from, with the checksum of the source.
            records.append(dict(source=str(path.resolve()), output=str(out.resolve()),
                                source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                crop='y=0:512,x=0:512'))
    destination.with_suffix('.json').write_text(json.dumps(records, indent=2))
    print(f'Created {len(records)} crops in {destination}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    make_fixture(args.images, args.destination)
