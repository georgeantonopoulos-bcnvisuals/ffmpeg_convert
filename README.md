# BCN FFmpeg Web UI (dev lineage)

The supported app is the **ffmpeg Web UI** in [`ffmpeg_web/`](ffmpeg_web/): a
FastAPI + browser tool for converting image sequences (including ACES EXR) to
ProRes / H.264 / H.265.

Users launch it from **AYON**, which runs
`/mnt/studio/pipeline/packages/ffmpeg_web_bundle/run.sh`. Changes reach users only
after being ported into `/mnt/studio/pipeline/packages/ffmpeg_web_worktree` and
deployed with its `sync_to_bundle.sh`.

**Contributors and AI agents: read [`AGENTS.md`](AGENTS.md) first.** It lists what
is in scope. Everything outside `ffmpeg_web/` (the Tkinter `ffmpeg_ui.py`, its
launchers, `ffmpeg_ui_rez_package/`, PyInstaller/Nuitka specs, `_archive/`) is
legacy and must not be worked on.
