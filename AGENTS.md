# FFmpeg Web UI — Agent Guide

## 🛑 SCOPE RULE — READ FIRST

**The only product in this directory is the ffmpeg Web UI**: the FastAPI + browser
app that users start from the **AYON launcher**, which runs
`/mnt/studio/pipeline/packages/ffmpeg_web_bundle/run.sh` (rez package `ffmpeg_web`
nested inside that bundle). **This is the only thing agents may work on.**

Everything else here is **legacy / dead**. Do not modify, fix, build, deploy,
"modernise", or port features into any of it, even if a request sounds like it
applies (e.g. "fix the FFmpeg UI"). If a request seems to target legacy code, ask
the user before touching it — the answer is almost always "do it in the web UI".

| Status | Path | What it is |
| :--- | :--- | :--- |
| ✅ **IN SCOPE** | `ffmpeg_web/` | Web UI source (dev lineage). Port finished changes into the studio worktree. |
| ✅ **IN SCOPE** | `/mnt/studio/pipeline/packages/ffmpeg_web_worktree` | Studio lineage — where changes must land to reach users. |
| ❌ legacy | `ffmpeg_ui.py`, `dark_theme.tcl`, `rounded_buttons.tcl`, `ffmpeg_ui_icon.png` | Tkinter desktop app. Superseded. |
| ❌ legacy | `launch_ffmpeg_ui.py`, `run_ffmpeg_ui.sh`, `update_ffmpeg_ui.sh` | Tkinter launchers / deploy-to-`ffmpeg_UI` script. |
| ❌ legacy | `ffmpeg_ui_rez_package/`, rez pkg `ffmpeg_UI`, `ayon/launch_scripts/launch_ffmpeg_ui.sh` | Tkinter packaging. Frozen Dec 2025. |
| ❌ legacy | `ffmpeg_ui.spec`, `_archive/` (Nuitka/PyInstaller builds, Qt `ffmpeg_converter.py`) | Abandoned standalone-binary experiments. |
| ❌ not a target | `ffmpeg_web_bundle/` (here), `make_bundle.sh` | Local, gitignored build artifact. **Never** copy it to the studio share. |
| ⚪ dev only | `launch_web_ui.py` | Local rez launcher for testing the dev lineage. Not how users launch. |

Rejected directions — do not propose or resume them: PyInstaller/Nuitka one-file
binaries, Apptainer images, conda-pack bundles, the Qt converter, or any further
Tkinter work.

---

## 1. Deployment topology

**Editing this repo changes nothing for users.** Verify the deployment target
before scoping any work.

| Thing | Path | Notes |
| :--- | :--- | :--- |
| **Live web UI (what users run)** | `/mnt/studio/pipeline/packages/ffmpeg_web_bundle` | Separate git repo: `github.com/georgeantonopoulos-bcnvisuals/ffmpeg_web_bundle`. AYON runs its `run.sh`. |
| **Edit here to change it** | `/mnt/studio/pipeline/packages/ffmpeg_web_worktree` | git worktree of that repo (has its own `AGENTS.md`) |
| **Deploy script** | `ffmpeg_web_worktree/sync_to_bundle.sh` | rsyncs `packages/ffmpeg_web/1.0.0/{python,bin,lib}` into the live bundle |
| **This dev repo** | `/mnt/production/user/.../DEV/ffmpeg_convert` | Different lineage of `ffmpeg_web/`; a staging area, not a deploy source |

**The two web lineages have diverged.** The studio worktree carries features this
repo lacks (CUDA/NVENC via `hwupload_cuda`, VLC playback, open-output-folder,
reveal-in-folder). **Never rsync this repo over the worktree** — port changes into
it and reconcile by hand.

Do not infer which app is current from a script's name: `launch_ffmpeg_ui.sh`
starts the *legacy Tkinter* app, and AYON's web-UI entry is configured inside AYON
itself, so grepping `ayon/launch_scripts/` for `ffmpeg_web` finds nothing.

When a deployed change seems missing, first ask whether the user sees a **browser
tab** (web UI) or a **desktop window** (legacy Tkinter), then rule out a cached
`index.html` before re-syncing.

---

## 2. Web UI overview

A browser-based UI for **FFmpeg** tailored to studio delivery: **ACES** colour
conversion of EXR sequences, image-sequence handling, and ProRes / H.264 / H.265
encoding.

- **Backend** — `ffmpeg_web/main.py` (FastAPI, served by uvicorn):
  - `/api/settings` (GET/POST): shared JSON settings.
  - `/api/browse`, `/api/scan`: server-side file browser and `clique` sequence detection.
  - `/api/convert`, `/api/cancel`, `/api/cleanup`: conversion jobs and EXR temp cleanup.
  - `/api/deps`: dependency health (`oiiotool`, `clique`) via `core/deps.py`.
  - WebSocket `/ws/status`: streams FFmpeg/EXR logs and progress.
- **Frontend** — `ffmpeg_web/static/` (`index.html`, `style.css`, `js/api.js`, `js/ui.js`).
- **External tools** — FFmpeg, OpenImageIO `oiiotool`, OCIO config at
  `/mnt/studio/config/ocio/aces_1.2/config.ocio`. In the live bundle these ship in
  `packages/ffmpeg_web/1.0.0/{bin,lib}`.

```
ffmpeg_web/
├── main.py               # FastAPI app, WebSocket, job manager
├── config.py             # Settings load/save helpers
├── core/
│   ├── ffmpeg_handler.py # FFmpeg command building/execution
│   ├── exr_handler.py    # EXR → PNG via oiiotool + OCIO
│   ├── explorer.py       # File browser + clique sequence detection
│   ├── reformat.py       # Output resolution: probe, aspect math, filter settings
│   ├── timing.py         # Frame rates, exact durations, retime (Fraction maths)
│   ├── version.py        # Build stamp / stale-code detection
│   └── deps.py           # Dependency health checks (/api/deps)
├── static/               # index.html, style.css, js/, images/
└── test_*.py             # Framework-free test suites (plain asserts)
```

### Tests

Three copies of `ffmpeg_web` exist on disk (this repo, worktree, bundle) and Python
will silently import the wrong one. Run suites with `python -m ffmpeg_web.test_<name>`
from the lineage's own directory, and **assert `ffmpeg_web.__file__`** points at the
lineage you mean before trusting a result. `test_api` needs a running server; the
rest (`test_codec`, `test_reformat`, `test_explorer`, `test_colorspace`,
`test_version`, `test_cache`, `test_timing`) do not.

---

## 3. Development journal (web UI)

### Feb 2026: FastAPI Web UI port
Browser UI mirroring the old Tkinter workflow, local-only and studio-friendly.
Replaced the Tkinter app, which is now legacy.

### Aug 2026: Output reformat (resolution) support
- **UI**: `Reformat Resolution` checkbox in *Output Settings*, off by default;
  reveals Width/Height (blank = derived from source aspect). Live hint shows
  `Source: W x H -> Output: W x H`.
- **EXR** sequences resize inside the `oiiotool` pre-pass with
  `--resize:filter=lanczos3:highlightcomp=1`, after `--ch R,G,B` and **before**
  `--colorconvert`, so filtering happens on scene-linear ACEScg float;
  `highlightcomp` stops bright HDR pixels ringing into dark halos.
- **Everything else** extends the existing trailing `scale` filter with
  `w=..:h=..:flags=lanczos+accurate_rnd+full_chroma_int` — one swscale pass, not two.
- **Double-resize guard**: the EXR pre-pass clears `reformat_enabled` after
  pointing the job at its temp PNGs.
- **Even dimensions**: sizes round *up* to even (`yuv420p` needs it).
- **Source resolution** is probed with `oiiotool --info` (fallback `ffmpeg -i`);
  the backend always re-probes and never trusts client numbers.

### Sep 2026
- ACES output transform choice (sRGB or Rec.709).
- H.264 level declared correctly; user-selectable level (5.0 / 5.1 / 6.1).
- Encoder settings shown in the UI; stale running code detected via `core/version.py`.
- UI modernised; BCN logo restored (the logo originates in the studio lineage).
- **Frame rate & duration** (`core/timing.py`): FPS fields are dropdowns
  (23.976, 24, 25, 29.97, 30, 50, 59.94, 60) sending exact rationals
  (`24000/1001`). The content is always retimed to *exactly* the requested
  seconds. A file holds whole frames, so at whole rates it is exact (10 s @
  30 = 300 frames = 10.000 s) and at NTSC the partial last frame is dropped
  (10 s @ 29.97 = 299 frames = 9.977 s), with a warning in the UI and log.
  **Out-of-home players that demand an exact duration need 25/30 fps** —
  no FFmpeg flag can make NTSC hit whole seconds. `-video_track_timescale`
  makes each *frame* exact, not the total.
