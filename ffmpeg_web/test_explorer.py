"""Tests for sequence detection, including selecting a single frame.

Framework-free like the other test modules here, and needs no server.

Run:
    python -m ffmpeg_web.test_explorer
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .core import explorer


def _make_sequence(folder: str, head: str, frames, width: int = 64, height: int = 64) -> None:
    """Write a tiny image sequence with oiiotool."""
    os.makedirs(folder, exist_ok=True)
    seed = os.path.join(folder, f".seed_{head}.png")
    subprocess.run(
        ["oiiotool", "--create", f"{width}x{height}", "3", "-d", "uint8", "-o", seed],
        check=True,
        capture_output=True,
    )
    for frame in frames:
        shutil.copy(seed, os.path.join(folder, f"{head}.{frame:04d}.png"))
    os.remove(seed)


def _fixture():
    """Two distinct sequences in one folder, at different resolutions."""
    tmp = tempfile.mkdtemp(prefix="ffmpeg_web_explorer_")
    _make_sequence(tmp, "plateA", range(1, 6), width=64, height=32)
    _make_sequence(tmp, "plateB", range(100, 105), width=48, height=24)
    return tmp


def test_directory_scan_finds_every_sequence() -> None:
    """Selecting a folder still returns all sequences in it."""
    tmp = _fixture()
    try:
        seqs = explorer.scan_for_sequences(tmp)
        heads = sorted(s.head.rstrip("._") for s in seqs)
        assert heads == ["plateA", "plateB"], heads
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_selecting_a_frame_returns_its_sequence_first() -> None:
    """Picking any frame of a sequence puts that sequence first."""
    tmp = _fixture()
    try:
        frame = os.path.join(tmp, "plateB.0102.png")
        seqs = explorer.scan_for_sequences(frame)
        assert seqs, "expected at least one sequence"
        assert seqs[0].head.rstrip("._") == "plateB", seqs[0].head
        assert seqs[0].start == 100 and seqs[0].end == 104, (seqs[0].start, seqs[0].end)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_selecting_the_first_frame_works_too() -> None:
    """The first frame is not a special case."""
    tmp = _fixture()
    try:
        seqs = explorer.scan_for_sequences(os.path.join(tmp, "plateA.0001.png"))
        assert seqs[0].head.rstrip("._") == "plateA", seqs[0].head
        assert seqs[0].start == 1 and seqs[0].end == 5, (seqs[0].start, seqs[0].end)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_selecting_a_frame_still_returns_the_other_sequences() -> None:
    """The other sequences remain available, just not first."""
    tmp = _fixture()
    try:
        seqs = explorer.scan_for_sequences(os.path.join(tmp, "plateA.0003.png"))
        heads = sorted(s.head.rstrip("._") for s in seqs)
        assert heads == ["plateA", "plateB"], heads
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_selected_sequence_is_the_one_probed_for_resolution() -> None:
    """The probed resolution must belong to the sequence the user picked."""
    tmp = _fixture()
    try:
        seqs = explorer.scan_for_sequences(os.path.join(tmp, "plateB.0101.png"))
        assert (seqs[0].width, seqs[0].height) == (48, 24), (seqs[0].width, seqs[0].height)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_path_returns_no_sequences() -> None:
    """A path that does not exist must not raise."""
    assert explorer.scan_for_sequences("/nonexistent/definitely/not/here") == []


def main() -> None:
    """Run every test and print a pass/fail line for each."""
    if not shutil.which("oiiotool"):
        print("[SKIP] oiiotool not on PATH; these tests need it to make fixtures")
        raise SystemExit(0)

    tests = [
        ("directory scan finds all", test_directory_scan_finds_every_sequence),
        ("frame selects its sequence", test_selecting_a_frame_returns_its_sequence_first),
        ("first frame works too", test_selecting_the_first_frame_works_too),
        ("others still returned", test_selecting_a_frame_still_returns_the_other_sequences),
        ("selected one is probed", test_selected_sequence_is_the_one_probed_for_resolution),
        ("missing path is empty", test_missing_path_returns_no_sequences),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"[OK]   {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {name}: {exc}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
