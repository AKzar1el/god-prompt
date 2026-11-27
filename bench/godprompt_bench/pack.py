"""Create a portable public-only ZIP from an already exported benchmark run.

This is offline packaging, not model execution or provenance authentication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .review import _PUBLIC_ARTIFACTS, _read_bounded, review_result


def _check_destination(destination: Path) -> None:
    if destination.suffix.lower() != ".zip":
        raise ValueError("public evidence output must have a .zip extension")
    if destination.exists() or destination.is_symlink():
        raise ValueError("public evidence ZIP destination already exists")
    if not destination.parent.is_dir():
        raise ValueError("public evidence ZIP parent directory does not exist")
    # A linked parent can redirect a seemingly local output to another tree.
    for candidate in (destination.parent, *destination.parent.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ValueError("refusing linked public ZIP output directory")


def pack_public_evidence(source: Path, destination: Path) -> dict[str, object]:
    """Validate a saved run, then atomically create exactly three public ZIP entries."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source must be a non-linked benchmark result directory")
    _check_destination(destination)
    reviewed = review_result(source)
    snapshots: dict[str, bytes] = {}
    for name, maximum in _PUBLIC_ARTIFACTS:
        path = source / name
        data = _read_bounded(path, maximum)
        if hashlib.sha256(data).hexdigest() != reviewed["public_artifact_sha256"][name]:
            raise ValueError(f"public artifact changed since review: {name}")
        snapshots[name] = data

    # Create in the same directory and publish by an exclusive hard link:
    # unlike replace/rename, this cannot overwrite an existing owner file.
    with TemporaryDirectory(prefix="godprompt_public_pack_", dir=destination.parent) as temp:
        pending = Path(temp) / "public.zip"
        with ZipFile(pending, "w", compression=ZIP_DEFLATED, compresslevel=6) as output:
            for name, _ in _PUBLIC_ARTIFACTS:
                member = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                member.create_system = 3
                member.external_attr = (stat.S_IFREG | 0o644) << 16
                output.writestr(member, snapshots[name], compress_type=ZIP_DEFLATED, compresslevel=6)
        digest = hashlib.sha256(pending.read_bytes()).hexdigest()
        _check_destination(destination)
        os.link(pending, destination)
    return {
        "public_zip": str(destination),
        "public_zip_sha256": digest,
        "public_artifact_sha256": reviewed["public_artifact_sha256"],
        "review_only": True,
        "performance_claim_verified": False,
        "cautions": reviewed["cautions"],
        "private_trajectories_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package a validated, existing benchmark export into a public-only ZIP offline"
    )
    parser.add_argument("result_dir", type=Path, help="Existing result directory (never a ZIP)")
    parser.add_argument("output_zip", type=Path, help="New .zip path; existing files are never replaced")
    args = parser.parse_args()
    try:
        receipt = pack_public_evidence(args.result_dir, args.output_zip)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
