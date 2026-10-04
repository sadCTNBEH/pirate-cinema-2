import os
from backend.config import get_data_dir
import subprocess
import json
import uuid
import time
import traceback
import logging

logger = logging.getLogger('mpv')
logger.setLevel(logging.DEBUG)
import threading
from urllib.parse import quote

class MPVController:
    def __init__(self):
        self.process = None
        self.pipe = None
        self.pipe_name = None
        self.thread = None
        self.on_progress = None
        self.on_end = None
        self.is_running = False

    def launch(self, mpv_path: str, url: str, title: str, start_time: int = 0, audio_track: int = 0):
        if self.is_running:
            self.stop()
            
        pipe_id = str(uuid.uuid4())
        if os.name == 'nt':
            self.pipe_name = f"\\\\.\\pipe\\mpv-ipc-{pipe_id}"
        else:
            self.pipe_name = f"/tmp/mpv-ipc-{pipe_id}"
            
        args = [
            mpv_path,
            "--fs",
            "--ontop",
            "--force-window=immediate",
            "--idle=once",
            "--keep-open=yes",
            "--msg-level=all=no,cplayer=info",
            f"--input-ipc-server={self.pipe_name}"
        ]
        
        if os.name == 'nt':
            args.extend(["--gpu-api=opengl", "--gpu-context=win", "--hwdec=d3d11va-copy"])
            
        
        print(f"[MPV] Launching with args: {args}")
        try:
            log_path = get_data_dir() / "mpv_debug.log"
            self.log_file = open(log_path, "w", encoding="utf-8")
            self.process = subprocess.Popen(args, stdout=self.log_file, stderr=subprocess.STDOUT)
            print(f"[MPV] Process started with PID {self.process.pid}")
        except Exception as e:
            print(f"[MPV] Failed to start process: {e}")
            traceback.print_exc()
            raise

        
        # Wait for pipe to be ready
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if os.name == 'nt':
                    self.pipe = open(self.pipe_name, "r+b", buffering=0)
                else:
                    import socket
                    self.pipe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.pipe.connect(self.pipe_name)
                break
            except Exception:
                time.sleep(0.1)
                
        if not self.pipe:
            self.process.kill()
            raise Exception("Failed to connect to MPV IPC")
            
        self.is_running = True
        
        # Load file
        self.send_command(["set_property", "start", str(start_time)])
        self.send_command(["set_property", "force-media-title", title])
        if audio_track:
            self.send_command(["set_property", "aid", audio_track])
        self.send_command(["observe_property", 1, "time-pos"])
        self.send_command(["observe_property", 2, "duration"])
        self.send_command(["observe_property", 3, "aid"])
        self.send_command(["loadfile", url, "replace"])
        
        # Start reading thread
        self.thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.thread.start()
        
    def send_command(self, command):
        if not self.pipe:
            return
        payload = json.dumps({"command": command}) + "\n"
        try:
            if os.name == 'nt':
                self.pipe.write(payload.encode('utf-8'))
            else:
                self.pipe.sendall(payload.encode('utf-8'))
        except Exception as e:
            print("Failed to send command to MPV:", e)

    def _reader_loop(self):
        print("[MPV] Reader loop started.")
        # We need a file-like object for easy readline reading
        if os.name == 'nt':
            f = self.pipe
        else:
            f = self.pipe.makefile("rb")
            
        try:
            while self.is_running:
                line = f.readline()
                if not line:
                    break
                data = json.loads(line.decode('utf-8'))
                if "event" in data:
                    if data["event"] == "property-change" and data.get("name") in ("time-pos", "duration", "aid"):
                        if self.on_progress:
                            self.on_progress(data["name"], data.get("data"))
                    elif data["event"] == "end-file":
                        if self.on_end:
                            self.on_end(data.get('reason'))
        except Exception as e:
            print(f"[MPV] Reader loop exception: {e}")
            traceback.print_exc()
        finally:
            print("[MPV] Reader loop exiting.")
            if self.on_progress:
                self.on_progress("flush", True)
            self.stop()
            
    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
        if self.pipe:
            try:
                self.pipe.close()
            except Exception:
                pass
        if os.name != 'nt' and self.pipe_name and os.path.exists(self.pipe_name):
            try:
                os.remove(self.pipe_name)
            except Exception:
                pass
        self.process = None
        self.pipe = None
