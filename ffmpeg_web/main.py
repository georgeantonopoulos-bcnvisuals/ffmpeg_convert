import os
import asyncio
import json
import logging
import threading
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config
from .core import explorer
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

# --- Connection Manager for WebSockets ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# --- Job Manager ---
class JobManager:
    def __init__(self):
        self.is_running = False
        self.ffmpeg_handler = FFmpegHandler(self._log_callback)
        self.exr_handler = ExrHandler(self._log_callback)
        self.current_thread: Optional[threading.Thread] = None
        self.loop = None # Reference to the event loop for broadcasting

    def _log_callback(self, msg_type: str, content: str):
        """Called by handlers to stream logs."""
        if self.loop:
            # Schedule broadcasting on the main event loop
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": msg_type, "content": content}), 
                self.loop
            )

    def start_job(self, config_data: FFmpegJobConfig):
        if self.is_running:
            raise HTTPException(status_code=400, detail="A job is already running")
        
        self.is_running = True
        self.loop = asyncio.get_running_loop()
        
        # Determine if EXR Pre-pass is needed
        is_exr = config_data.filename_pattern.lower().endswith('.exr')
        
        # Start background thread
        self.current_thread = threading.Thread(
            target=self._run_job_thread, 
            args=(config_data, is_exr)
        )
        self.current_thread.start()

    def _run_job_thread(self, job_config: FFmpegJobConfig, is_exr: bool):
        try:
            temp_dir = ""
            
            # 1. EXR Conversion Pass
            if is_exr:
                self._log_callback('output', "Starting EXR Conversion Phase...\n")
                
                # Setup EXR Handler
                temp_dir = self.exr_handler.convert_exr_sequence(
                    input_folder=job_config.input_folder,
                    pattern=job_config.filename_pattern,
                    start_frame=job_config.start_frame,
                    end_frame=job_config.end_frame
                )
                
                if not temp_dir or self.exr_handler.is_cancelled:
                    if not self.exr_handler.is_cancelled:
                        self._log_callback('error', "EXR Conversion failed.")
                    self.is_running = False
                    return

                # Update config for FFmpeg Pass
                # Point to temp PNG sequence
                # Assuming oiiotool output pattern logic from exr_handler (prefix + %04d.png)
                prefix = job_config.filename_pattern.split('%')[0]
                job_config.input_folder = temp_dir
                job_config.filename_pattern = f"{prefix}%04d.png"
                
                self._log_callback('output', "EXR Phase Complete. Starting FFmpeg Phase...\n")

            # 2. FFmpeg Pass (Skipped if cancelled)
            if not self.is_running: # Check cancellation again
                return

            self.ffmpeg_handler.run_ffmpeg(job_config)

            # 3. Cleanup
            if is_exr and temp_dir:
                self.exr_handler.cleanup()

        except Exception as e:
             self._log_callback('error', f"Critical Job Error: {e}")
        finally:
            self.is_running = False
            self._log_callback('job_status', 'idle')

    def cancel_job(self):
        if not self.is_running:
            return
        
        self._log_callback('output', "Cancelling job...\n")
        
        # Signal both handlers
        self.ffmpeg_handler.cancel()
        self.exr_handler.cancel()
        
        # The thread will exit naturally after handlers abort

job_manager = JobManager()


# --- Endpoints ---

@app.get("/")
async def read_root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Backend running. Please install frontend files."}

@app.get("/api/settings")
async def get_settings():
    return config.load_settings()

@app.post("/api/settings")
async def update_settings(settings: dict):
    config.save_settings(settings)
    return {"status": "success"}

@app.get("/api/browse")
async def browse(path: str = ""):
    return explorer.get_directory_contents(path)

@app.post("/api/scan")
async def scan(payload: dict = Body(...)):
    folder = payload.get("path")
    if not folder:
        raise HTTPException(status_code=400, detail="Path required")
    return explorer.scan_for_sequences(folder)

@app.post("/api/convert")
async def start_conversion(job_config: FFmpegJobConfig):
    job_manager.start_job(job_config)
    return {"status": "started"}

@app.post("/api/cancel")
async def cancel_job():
    job_manager.cancel_job()
    return {"status": "cancelling"}

@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, maybe implement ping/pong or process commands if needed
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
