"""Unit tests for codec selection and encoder parameters.

Framework-free like ``test_reformat.py`` and needing no running server:
everything here is pure function testing.  The one test that shells out
to ``ffmpeg`` is skipped when the binary is not on PATH.

Run:
    python -m ffmpeg_web.test_codec
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .core.exr_handler import build_frame_command
from .core.ffmpeg_handler import (
    BITRATE_CODECS,
    build_bitrate_codec_params,
    exr_bit_depth_for_codec,
    select_encoder,
)


# A machine where every NVENC encoder is available, so the tests below
# prove h264_h10 declines NVENC by choice rather than by absence.
GPU_ALL = {
    "nvidia_gpu": True,
    "nvenc_h264": True,
    "nvenc_hevc": True,
    "hwupload_cuda": True,
    "gpu_name": "Test GPU",
}
GPU_NONE = {
    "nvidia_gpu": False,
    "nvenc_h264": False,
    "nvenc_hevc": False,
    "hwupload_cuda": False,
}


# --- select_encoder() -------------------------------------------------------

def test_h264_h10_never_uses_nvenc() -> None:
    """NVIDIA's H.264 encoder has no 10-bit mode, so High 10 must stay on CPU.

    This is the important one: even with h264_nvenc advertised as
    available, a 10-bit request has to fall back to libx264 or FFmpeg
    fails at runtime with an unsupported pixel format.
    """
    assert select_encoder("h264_h10", GPU_ALL) == ("libx264", False)


def test_h264_still_uses_nvenc_when_available() -> None:
    """The existing 8-bit H.264 GPU path must not regress."""
    assert select_encoder("h264", GPU_ALL) == ("h264_nvenc", True)


def test_h265_still_uses_nvenc_when_available() -> None:
    """The existing H.265 GPU path must not regress."""
    assert select_encoder("h265", GPU_ALL) == ("hevc_nvenc", True)


def test_h264_falls_back_to_libx264_without_gpu() -> None:
    assert select_encoder("h264", GPU_NONE) == ("libx264", False)


def test_h265_falls_back_to_libx265_without_gpu() -> None:
    assert select_encoder("h265", GPU_NONE) == ("libx265", False)


def test_h264_h10_uses_libx264_without_gpu_too() -> None:
    assert select_encoder("h264_h10", GPU_NONE) == ("libx264", False)


# --- pixel format -----------------------------------------------------------

def test_h264_h10_encodes_ten_bit() -> None:
    """High 10 is only meaningful with a 10-bit pixel format."""
    _, pix_fmt = build_bitrate_codec_params("h264_h10", "libx264", False, "30")
    assert pix_fmt == "yuv420p10le"


def test_h264_stays_eight_bit() -> None:
    _, pix_fmt = build_bitrate_codec_params("h264", "libx264", False, "30")
    assert pix_fmt == "yuv420p"


def test_h265_stays_eight_bit() -> None:
    _, pix_fmt = build_bitrate_codec_params("h265", "libx265", False, "30")
    assert pix_fmt == "yuv420p"


# --- profile / tagging ------------------------------------------------------

def test_h264_h10_requests_high10_profile() -> None:
    params, _ = build_bitrate_codec_params("h264_h10", "libx264", False, "30")
    assert "high10" in params
    assert "-profile:v" in params
    assert params[params.index("-profile:v") + 1] == "high10"


def test_h264_h10_is_never_tagged_as_hevc() -> None:
    """The old ``if h264 / else`` branch would have tagged this hvc1.

    An H.264 bitstream carrying an HEVC tag confuses players, so guard
    the exact regression the third codec introduced.
    """
    params, _ = build_bitrate_codec_params("h264_h10", "libx264", False, "30")
    assert "hvc1" not in params
    assert "-tag:v" not in params


def test_h265_is_still_tagged_hvc1() -> None:
    params, _ = build_bitrate_codec_params("h265", "libx265", False, "30")
    assert params[params.index("-tag:v") + 1] == "hvc1"


def test_h264_cpu_params_are_unchanged() -> None:
    """Pin today's exact 8-bit H.264 command so the refactor is provably inert."""
    params, pix_fmt = build_bitrate_codec_params("h264", "libx264", False, "30")
    assert params == [
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", "30M",
        "-minrate", "30M",
        "-maxrate", "30M",
        "-bufsize", "30M",
        "-x264-params", "nal-hrd=cbr",
        "-profile:v", "high",
        "-level:v", "5.1",
    ]
    assert pix_fmt == "yuv420p"


def test_h265_cpu_params_are_unchanged() -> None:
    params, _ = build_bitrate_codec_params("h265", "libx265", False, "30")
    assert params == [
        "-c:v", "libx265",
        "-preset", "medium",
        "-b:v", "30M",
        "-minrate", "30M",
        "-maxrate", "30M",
        "-bufsize", "30M",
        "-tag:v", "hvc1",
    ]


def test_h264_nvenc_params_are_unchanged() -> None:
    """The GPU path must survive the restructure byte for byte."""
    params, _ = build_bitrate_codec_params("h264", "h264_nvenc", True, "30")
    assert params == [
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-tune", "hq",
        "-rc", "cbr",
        "-b:v", "30M",
        "-maxrate", "30M",
        "-bufsize", "60M",
        "-profile:v", "high",
        "-level:v", "5.1",
    ]


def test_h264_h10_carries_cbr_bitrate_like_its_siblings() -> None:
    params, _ = build_bitrate_codec_params("h264_h10", "libx264", False, "45")
    assert params[params.index("-b:v") + 1] == "45M"
    assert params[params.index("-maxrate") + 1] == "45M"


# --- codec family membership ------------------------------------------------

def test_h264_h10_is_a_bitrate_codec() -> None:
    """It shares the Mbps control with h264/h265 rather than a qscale."""
    assert "h264_h10" in BITRATE_CODECS
    assert "h264" in BITRATE_CODECS
    assert "h265" in BITRATE_CODECS


def test_prores_is_not_a_bitrate_codec() -> None:
    assert "prores_422" not in BITRATE_CODECS
    assert "qtrle" not in BITRATE_CODECS


# --- EXR intermediate bit depth ---------------------------------------------

def test_ten_bit_codec_asks_for_sixteen_bit_exr_frames() -> None:
    """Without this the 10-bit encode would carry 8-bit data.

    The oiiotool pre-pass is where the depth is actually decided; a
    uint8 PNG makes High 10 pure overhead for EXR sources.
    """
    assert exr_bit_depth_for_codec("h264_h10") == "uint16"


def test_eight_bit_codecs_keep_uint8_exr_frames() -> None:
    """Existing codecs must not silently double their temp disk usage."""
    assert exr_bit_depth_for_codec("h264") == "uint8"
    assert exr_bit_depth_for_codec("h265") == "uint8"
    assert exr_bit_depth_for_codec("prores_422") == "uint8"


def test_frame_command_defaults_to_eight_bit() -> None:
    """Callers that never pass a depth keep today's behaviour."""
    cmd = build_frame_command("in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", None)
    assert cmd[cmd.index("-d") + 1] == "uint8"


def test_frame_command_accepts_sixteen_bit() -> None:
    cmd = build_frame_command(
        "in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", None, bit_depth="uint16"
    )
    assert cmd[cmd.index("-d") + 1] == "uint16"


def test_frame_command_bit_depth_does_not_disturb_resize_order() -> None:
    """The resize must still precede the colour convert at 16-bit."""
    cmd = build_frame_command(
        "in.exr", "out.png", "cfg.ocio", "ACES - ACEScg", (960, 540), bit_depth="uint16"
    )
    resize = next(i for i, a in enumerate(cmd) if a.startswith("--resize"))
    assert resize < cmd.index("--colorconvert")
    assert cmd[cmd.index("-d") + 1] == "uint16"


# --- end-to-end encode ------------------------------------------------------

def test_ffmpeg_actually_produces_a_high10_file() -> None:
    """Prove the bundled encoder supports what we ask of it.

    Skipped when ffmpeg is absent so the suite stays runnable anywhere.
    """
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("       (skipped: ffmpeg/ffprobe not on PATH)")
        return

    params, pix_fmt = build_bitrate_codec_params("h264_h10", "libx264", False, "5")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "h10.mp4")
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=128x128:rate=5",
            "-frames:v", "5", "-pix_fmt", pix_fmt,
        ] + params + ["-y", out]
        subprocess.run(cmd, check=True, capture_output=True)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=profile,pix_fmt,codec_name",
             "-of", "default=nw=1:nk=1", out],
            check=True, capture_output=True, text=True,
        ).stdout.split()

    assert "h264" in probe, probe
    assert "High 10" in " ".join(probe), probe
    assert "yuv420p10le" in probe, probe


def main() -> None:
    tests = [
        ("h264_h10 never uses nvenc", test_h264_h10_never_uses_nvenc),
        ("h264 still uses nvenc", test_h264_still_uses_nvenc_when_available),
        ("h265 still uses nvenc", test_h265_still_uses_nvenc_when_available),
        ("h264 cpu fallback", test_h264_falls_back_to_libx264_without_gpu),
        ("h265 cpu fallback", test_h265_falls_back_to_libx265_without_gpu),
        ("h264_h10 cpu without gpu", test_h264_h10_uses_libx264_without_gpu_too),
        ("h264_h10 is 10-bit", test_h264_h10_encodes_ten_bit),
        ("h264 stays 8-bit", test_h264_stays_eight_bit),
        ("h265 stays 8-bit", test_h265_stays_eight_bit),
        ("h264_h10 high10 profile", test_h264_h10_requests_high10_profile),
        ("h264_h10 not tagged hevc", test_h264_h10_is_never_tagged_as_hevc),
        ("h265 tagged hvc1", test_h265_is_still_tagged_hvc1),
        ("h264 cpu params unchanged", test_h264_cpu_params_are_unchanged),
        ("h265 cpu params unchanged", test_h265_cpu_params_are_unchanged),
        ("h264 nvenc params unchanged", test_h264_nvenc_params_are_unchanged),
        ("h264_h10 cbr bitrate", test_h264_h10_carries_cbr_bitrate_like_its_siblings),
        ("h264_h10 in bitrate family", test_h264_h10_is_a_bitrate_codec),
        ("prores not in bitrate family", test_prores_is_not_a_bitrate_codec),
        ("10-bit codec wants uint16", test_ten_bit_codec_asks_for_sixteen_bit_exr_frames),
        ("8-bit codecs keep uint8", test_eight_bit_codecs_keep_uint8_exr_frames),
        ("frame command defaults uint8", test_frame_command_defaults_to_eight_bit),
        ("frame command accepts uint16", test_frame_command_accepts_sixteen_bit),
        ("bit depth keeps resize order", test_frame_command_bit_depth_does_not_disturb_resize_order),
        ("ffmpeg produces High 10", test_ffmpeg_actually_produces_a_high10_file),
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
