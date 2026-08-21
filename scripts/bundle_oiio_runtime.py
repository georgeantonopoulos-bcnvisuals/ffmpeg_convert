#!/usr/bin/env python3
"""Copy the complete non-glibc ELF dependency closure for oiiotool.

The studio OpenImageIO package was built against Rocky Linux libraries which
are not declared accurately by its Rez recipe.  In particular, its binary
needs Boost 1.75 while Rez currently resolves Boost 1.81.  This helper builds
an isolated runtime by following ELF ``DT_NEEDED`` entries recursively.

Libraries are copied as real files under their SONAME so the result also works
on filesystems which do not preserve symbolic links (notably the SMB share).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


NEEDED_RE = re.compile(r"Shared library: \[(?P<name>[^]]+)\]")

# These are supplied by the Rocky 9 base ABI.  Shipping another glibc beside
# an executable is unsafe and can break NSS, locales, and process startup.
BASE_ABI_LIBRARIES = {
    "ld-linux-x86-64.so.2",
    "libanl.so.1",
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libnss_dns.so.2",
    "libnss_files.so.2",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
    "libutil.so.1",
}


def needed_libraries(binary: Path) -> list[str]:
    result = subprocess.run(
        ["readelf", "-d", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [match.group("name") for match in NEEDED_RE.finditer(result.stdout)]


def find_library(name: str, search_dirs: list[Path]) -> Path | None:
    for directory in search_dirs:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def copy_dependency_closure(
    executable: Path, output_dir: Path, search_dirs: list[Path]
) -> list[tuple[str, Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pending = needed_libraries(executable)
    copied: dict[str, Path] = {}

    while pending:
        name = pending.pop(0)
        if name in BASE_ABI_LIBRARIES or name in copied:
            continue

        source = find_library(name, [output_dir, *search_dirs])
        if source is None:
            searched = os.pathsep.join(str(path) for path in search_dirs)
            raise RuntimeError(f"Unable to resolve {name}; searched {searched}")

        destination = output_dir / name
        if source.parent != output_dir:
            # Dereference symlinks intentionally for SMB compatibility.
            shutil.copy2(source.resolve(), destination)

        copied[name] = source.resolve()
        pending.extend(needed_libraries(destination))

    return sorted(copied.items())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--search-dir",
        type=Path,
        action="append",
        dest="search_dirs",
        default=[],
        help="Library directory, in precedence order (repeatable)",
    )
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    search_dirs = [path for path in args.search_dirs if path.is_dir()]
    if not search_dirs:
        raise RuntimeError("No valid library search directories were supplied")

    copied = copy_dependency_closure(args.executable, args.output_dir, search_dirs)
    manifest = "".join(f"{name}\t{source}\n" for name, source in copied)
    if args.manifest:
        args.manifest.write_text(manifest, encoding="utf-8")
    else:
        sys.stdout.write(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
