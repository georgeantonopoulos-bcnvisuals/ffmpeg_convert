import os
import asyncio
import json
import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from . import config
from .core import explorer
from .core.deps import check_dependencies
from .core.ffmpeg_handler import FFmpegHandler, FFmpegJobConfig
from .core.exr_handler import ExrHandler

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ffmpeg_web")

app = FastAPI(title="FFmpeg Web UI")

# Base directory for static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Cached dependency status populated at startup.
DEPENDENCY_STATUS: Dict[str, Any] = {
    "ok": False,
    "issues": ["Dependency check has not run yet."],
    "details": {},
}


@app.on_event("startup")
async def startup_event() -> None:
    """FastAPI startup hook that performs an initial dependency check."""
    global DEPENDENCY_STATUS  # noqa: PLW0603
    DEPENDENCY_STATUS = check_dependencies(install_missing=False)
    if not DEPENDENCY_STATUS.get("ok", False):
        logger.warning("Dependency issues detected: %s", DEPENDENCY_STATUS.get("issues"))
    else:
        logger.info("All FFmpeg Web UI dependencies look healthy.")


# --- Connection Manager for WebSockets ---
class ConnectionManager:
    """Track active WebSocket clients and broadcast messages to them."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active list."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Send a JSON message to all connected WebSocket clients."""
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001
                # Drop any connections that error during send.
                try:
                    self.active_connections.remove(connection)
                except ValueError:
                    continue


manager = ConnectionManager()


# --- Job Manager ---
class JobManager:
    """Coordinate EXR pre-pass work and FFmpeg conversion jobs."""

    def __init__(self) -> None:
        self.is_running = False
        self.ffmpeg_handler = FFmpegHandler(self._log_callback)
        self.exr_handler = ExrHandler(self._log_callback)
        self.current_thread: Optional[threading.Thread] = None
        # Reference to the event loop for broadcasting from worker threads.
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def _log_callback(self, msg_type: str, content: str) -> None:
        """Called by handlers to stream logs back to all WebSocket clients."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": msg_type, "content": content}),
                self.loop,
            )

    def start_job(self, config_data: FFmpegJobConfig) -> None:
        """Start a new conversion job in a background thread."""
        if self.is_running:
            raise HTTPException(status_code=400, detail="A job is already running")

        # Determine if EXR pre-pass is needed before marking the job as running.
        is_exr = config_data.filename_pattern.lower().endswith(".exr")

        if is_exr:
            # Ensure EXR-specific dependencies (oiiotool) are available.
            status = DEPENDENCY_STATUS or check_dependencies(install_missing=False)
            oiiotool_info = status.get("details", {}).get("oiiotool", {})
            if not oiiotool_info.get("available"):
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "EXR conversion requires 'oiiotool' on PATH, "
                        "but it was not found. Please install OpenImageIO tools."
                    ),
                )

        self.is_running = True
        self.loop = asyncio.get_running_loop()

        # Start background thread
        self.current_thread = threading.Thread(
            target=self._run_job_thread,
            args=(config_data, is_exr),
            daemon=True,
        )
        self.current_thread.start()

    def _run_job_thread(self, job_config: FFmpegJobConfig, is_exr: bool) -> None:
        """Execute the EXR pre-pass (if any) and FFmpeg conversion."""
        import os as _os  # Local import to avoid polluting module namespace.

        temp_dir = ""
        exr_phase_started = False
        try:
            # 1. EXR Conversion Pass
            if is_exr:
                self._log_callback("output", "Starting EXR Conversion Phase...\n")
                exr_phase_started = True

                temp_dir = self.exr_handler.convert_exr_sequence(
                    input_folder=job_config.input_folder,
                    pattern=job_config.filename_pattern,
                    start_frame=job_config.start_frame,
                    end_frame=job_config.end_frame,
                )

                if not temp_dir or self.exr_handler.is_cancelled:
                    if not self.exr_handler.is_cancelled:
                        self._log_callback("error", "EXR Conversion failed.")
                    self.is_running = False
                    return

                # Update config for FFmpeg Pass
                # Point to temp PNG sequence
                # Assuming oiiotool output pattern logic from exr_handler (prefix + %04d.png)
                prefix = job_config.filename_pattern.split("%")[0]
                job_config.input_folder = temp_dir
                job_config.filename_pattern = f"{prefix}%04d.png"

                self._log_callback(
                    "output", "EXR Phase Complete. Starting FFmpeg Phase...\n"
                )

            # 2. FFmpeg Pass (Skipped if cancelled)
            if not self.is_running:
                return

            self.ffmpeg_handler.run_ffmpeg(job_config)

        except Exception as exc:  # noqa: BLE001
            self._log_callback("error", f"Critical Job Error: {exc}")
        finally:
            # 3. Cleanup (for EXR paths) and status reset
            if is_exr and exr_phase_started and self.exr_handler.temp_dir:
                try:
                    if _os.path.exists(self.exr_handler.temp_dir):
                        self.exr_handler.cleanup()
                except Exception as cleanup_exc:  # noqa: BLE001
                    self._log_callback(
                        "output",
                        f"Warning: problem during EXR temp cleanup: {cleanup_exc}\n",
                    )

            self.is_running = False
            self._log_callback("job_status", "idle")

    def cancel_job(self) -> None:
        """Signal the current job (if any) to cancel."""
        if not self.is_running:
            return

        self._log_callback("output", "Cancelling job...\n")

        # Signal both handlers
        self.ffmpeg_handler.cancel()
        self.exr_handler.cancel()
        # The worker thread will exit naturally once handlers abort.


job_manager = JobManager()


# --- Endpoints ---
@app.get("/")
async def read_root() -> Any:
    """Serve the main HTML frontend or a simple JSON message as a fallback."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Backend running. Please install frontend files."}


@app.get("/api/settings")
async def get_settings() -> Dict[str, Any]:
    """Return the current FFmpeg settings JSON."""
    return config.load_settings()


@app.post("/api/settings")
async def update_settings(settings: Dict[str, Any]) -> Dict[str, str]:
    """Persist new FFmpeg settings JSON to disk."""
    config.save_settings(settings)
    return {"status": "success"}


@app.get("/api/browse")
async def browse(path: str = "") -> Any:
    """List the contents of a directory for the file browser."""
    return explorer.get_directory_contents(path)


@app.post("/api/scan")
async def scan(payload: Dict[str, Any] = Body(...)) -> Any:
    """Scan a folder for image sequences using `clique`."""
    folder = payload.get("path")
    if not folder:
        raise HTTPException(status_code=400, detail="Path required")
    return explorer.scan_for_sequences(folder)


@app.post("/api/convert")
async def start_conversion(job_config: FFmpegJobConfig) -> Dict[str, str]:
    """Start a new conversion job with the provided configuration."""
    job_manager.start_job(job_config)
    return {"status": "started"}


@app.post("/api/cancel")
async def cancel_job() -> Dict[str, str]:
    """Request cancellation of the currently running job, if any."""
    job_manager.cancel_job()
    return {"status": "cancelling"}


@app.post("/api/cleanup")
async def cleanup_temp() -> Dict[str, str]:
    """Force cleanup of any temporary EXR conversion directory, if present."""
    job_manager.exr_handler.cleanup()
    return {"status": "cleanup_triggered"}


@app.get("/api/deps")
async def get_dependency_status() -> Dict[str, Any]:
    """Expose the cached dependency status for frontend health checks."""
    if not DEPENDENCY_STATUS or not DEPENDENCY_STATUS.get("details"):
        # Fallback in case startup has not run (e.g., in some test harness).
        status = check_dependencies(install_missing=False)
        return status
    return DEPENDENCY_STATUS


@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for streaming job logs and progress."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; payloads from the client are ignored for now.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

