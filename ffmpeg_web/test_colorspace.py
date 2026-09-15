"""Unit tests for the ACES output transform (ODT) selection.

Framework-free like the other suites. The final test shells out to
``oiiotool`` against the studio OCIO config and is skipped when either
is unavailable.

Run:
    python -m ffmpeg_web.test_colorspace
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .core.exr_handler import build_frame_command
from .core.ffmpeg_handler import (
    OUTPUT_TRANSFORMS,
    SRGB_ODT,
    REC709_ODT,
    default_output_transform_for_codec,
    resolve_output_transform,
)

OCIO_CONFIG = "/mnt/studio/config/ocio/aces_1.2/config.ocio"


def _odt_of(cmd: list) -> str:
    """The ODT is the argument after the input colour space."""
    i = cmd.index("--colorconvert")
    return cmd[i + 2]


# --- build_frame_command() --------------------------------------------------

def test_frame_command_defaults_to_srgb() -> None:
    """Callers that pass no transform keep the historical behaviour."""
    cmd = build_frame_command("in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", None)
    assert _odt_of(cmd) == "Output - sRGB"


def test_frame_command_accepts_rec709() -> None:
    cmd = build_frame_command(
        "in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", None,
        output_transform=REC709_ODT,
    )
    assert _odt_of(cmd) == "Output - Rec.709"


def test_frame_command_keeps_input_colour_space_first() -> None:
    """--colorconvert takes FROM then TO; swapping them inverts the image."""
    cmd = build_frame_command(
        "in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", None,
        output_transform=REC709_ODT,
    )
    i = cmd.index("--colorconvert")
    assert cmd[i + 1] == "ACES - ACEScg"
    assert cmd[i + 2] == "Output - Rec.709"


def test_transform_does_not_disturb_resize_order() -> None:
    """Resize must still happen in scene-linear, before the ODT."""
    cmd = build_frame_command(
        "in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", (960, 540),
        output_transform=REC709_ODT, bit_depth="uint16",
    )
    resize = next(i for i, a in enumerate(cmd) if a.startswith("--resize"))
    assert resize < cmd.index("--colorconvert")


def test_transform_and_bit_depth_are_independent() -> None:
    cmd = build_frame_command(
        "in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", None,
        output_transform=REC709_ODT, bit_depth="uint16",
    )
    assert _odt_of(cmd) == "Output - Rec.709"
    assert cmd[cmd.index("-d") + 1] == "uint16"


# --- per-codec defaults -----------------------------------------------------

def test_prores_defaults_to_rec709() -> None:
    """ProRes goes to editorial and grading, so it gets the broadcast ODT."""
    assert default_output_transform_for_codec("prores_422") == REC709_ODT
    assert default_output_transform_for_codec("prores_422_lt") == REC709_ODT
    assert default_output_transform_for_codec("prores_444") == REC709_ODT


def test_h264_family_defaults_to_srgb() -> None:
    """Review MP4s are watched on computer screens, so they get sRGB."""
    assert default_output_transform_for_codec("h264") == SRGB_ODT
    assert default_output_transform_for_codec("h265") == SRGB_ODT
    assert default_output_transform_for_codec("h264_h10") == SRGB_ODT


def test_qtrle_defaults_to_srgb() -> None:
    assert default_output_transform_for_codec("qtrle") == SRGB_ODT


def test_unknown_codec_falls_back_to_srgb() -> None:
    """An unrecognised codec must not crash the job."""
    assert default_output_transform_for_codec("something_new") == SRGB_ODT


# --- resolve_output_transform() ---------------------------------------------

def test_explicit_choice_beats_the_codec_default() -> None:
    """The dropdown is the point: a user pick must survive."""
    assert resolve_output_transform(REC709_ODT, "h264") == REC709_ODT
    assert resolve_output_transform(SRGB_ODT, "prores_422") == SRGB_ODT


def test_missing_choice_falls_back_to_codec_default() -> None:
    """A client that sends nothing still gets a sensible transform."""
    assert resolve_output_transform(None, "prores_422") == REC709_ODT
    assert resolve_output_transform("", "h264") == SRGB_ODT


def test_unknown_transform_is_rejected() -> None:
    """Fail fast rather than 300 frames into an oiiotool error."""
    for bad in ("Output - Nonsense", "sRGB", "../etc/passwd", "Output - Rec.2020"):
        try:
            resolve_output_transform(bad, "h264")
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")


def test_only_the_two_supported_transforms_are_offered() -> None:
    assert set(OUTPUT_TRANSFORMS) == {SRGB_ODT, REC709_ODT}


# --- real conversion --------------------------------------------------------

def test_the_two_transforms_really_differ() -> None:
    """Prove the option changes pixels, not just the command line.

    Mid grey (0.18 scene-linear) must land on a different code value
    under each ODT, otherwise the dropdown is decorative.
    """
    if not shutil.which("oiiotool") or not os.path.exists(OCIO_CONFIG):
        print("       (skipped: oiiotool or OCIO config unavailable)")
        return

    def encode(odt: str, tmp: str, tag: str) -> float:
        src = os.path.join(tmp, "grey.exr")
        subprocess.run(
            ["oiiotool", "--pattern", "constant:color=0.18,0.18,0.18", "8x8", "3",
             "-d", "half", "-o", src],
            check=True, capture_output=True,
        )
        # distinct names: build_frame_command passes --no-clobber, so
        # reusing one path would silently keep the first result.
        out = os.path.join(tmp, f"out_{tag}.exr")
        subprocess.run(
            build_frame_command(src, out, OCIO_CONFIG, "ACES - ACEScg", None,
                                output_transform=odt),
            check=True, capture_output=True,
        )
        stats = subprocess.run(["oiiotool", "--stats", out],
                               check=True, capture_output=True, text=True).stdout
        for line in stats.splitlines():
            if "Stats Avg:" in line:
                return float(line.split(":")[1].split()[0])
        raise AssertionError("could not read stats")

    with tempfile.TemporaryDirectory() as tmp:
        srgb = encode(SRGB_ODT, tmp, "srgb")
        rec709 = encode(REC709_ODT, tmp, "rec709")

    delta = abs(rec709 - srgb) * 255
    assert delta > 4, f"ODTs differ by only {delta:.1f}/255 - suspiciously similar"
    assert rec709 > srgb, (
        "Rec.709 encodes mid grey higher than sRGB (steeper inverse EOTF); "
        f"got sRGB={srgb:.4f} Rec.709={rec709:.4f}"
    )


def main() -> None:
    tests = [
        ("defaults to sRGB", test_frame_command_defaults_to_srgb),
        ("accepts Rec.709", test_frame_command_accepts_rec709),
        ("input colour space first", test_frame_command_keeps_input_colour_space_first),
        ("resize before ODT", test_transform_does_not_disturb_resize_order),
        ("transform and depth independent", test_transform_and_bit_depth_are_independent),
        ("prores -> Rec.709", test_prores_defaults_to_rec709),
        ("h264 family -> sRGB", test_h264_family_defaults_to_srgb),
        ("qtrle -> sRGB", test_qtrle_defaults_to_srgb),
        ("unknown codec -> sRGB", test_unknown_codec_falls_back_to_srgb),
        ("explicit choice wins", test_explicit_choice_beats_the_codec_default),
        ("missing choice uses default", test_missing_choice_falls_back_to_codec_default),
        ("unknown transform rejected", test_unknown_transform_is_rejected),
        ("only two transforms offered", test_only_the_two_supported_transforms_are_offered),
        ("ODTs really differ", test_the_two_transforms_really_differ),
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
