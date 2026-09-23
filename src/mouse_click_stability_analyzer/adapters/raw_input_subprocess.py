from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

class WindowsRawInputSubprocess:
    """
    Raw Input adapter that isolates native Win32 Raw Input handling
    into a helper Python process.

    Why:
    - avoids crashing the Tk UI process if ctypes / WndProc handling fails
    - provides global capture
    - separates device_source via Raw Input device path
    """

    def __init__(self, callback):
        self.callback = callback
        self.process = None
        self.reader_thread = None
        self.stderr_thread = None
        self.running = False
        self.last_error = ""

    def start(self):
        if self.running:
            return

        bridge = Path(__file__).with_name("raw_input_bridge.py")
        self.process = subprocess.Popen(
            [sys.executable, str(bridge)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        self.running = True
        self.reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.reader_thread.start()
        self.stderr_thread.start()

    def stop(self):
        self.running = False

        proc = self.process
        self.process = None
        if proc is None:
            return

        try:
            proc.terminate()
        except Exception:
            pass

        def _wait_bridge():
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        threading.Thread(target=_wait_bridge, daemon=True).start()

    def _read_stdout(self):
        if not self.process or not self.process.stdout:
            return

        for line in self.process.stdout:
            if not self.running:
                break

            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except Exception:
                continue

            if event.get("type") == "error":
                self.last_error = event.get("message", "")
                continue

            if event.get("type") == "ready":
                continue

            if event.get("type") == "mouse_button":
                try:
                    self.callback(event)
                except Exception:
                    pass

    def _read_stderr(self):
        if not self.process or not self.process.stderr:
            return

        for line in self.process.stderr:
            if not self.running:
                break

            line = line.strip()
            if line:
                self.last_error = line
