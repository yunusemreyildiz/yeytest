"""ADB wrapper for device interaction."""

from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.models import Screenshot


class ADBError(Exception):
    """ADB command failed."""
    pass


class ADBDevice:
    """Android device interaction via ADB."""

    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id
        self._validate_adb()

    def _validate_adb(self) -> None:
        """Check if ADB is available."""
        try:
            subprocess.run(
                ["adb", "version"],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError:
            raise ADBError("ADB not found. Please install Android SDK.")
        except subprocess.CalledProcessError as e:
            raise ADBError(f"ADB error: {e.stderr.decode()}")

    def _adb_cmd(self, *args: str) -> subprocess.CompletedProcess:
        """Run ADB command."""
        cmd = ["adb"]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.extend(args)
        
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise ADBError(f"ADB command failed: {result.stderr.decode()}")
        return result

    def get_devices(self) -> list[str]:
        """List connected devices."""
        result = self._adb_cmd("devices")
        lines = result.stdout.decode().strip().split("\n")[1:]
        devices = []
        for line in lines:
            if "\tdevice" in line:
                devices.append(line.split("\t")[0])
        return devices

    def screenshot(
        self,
        output_dir: Path,
        step_index: int,
        description: str = "",
    ) -> Screenshot:
        """Capture screenshot from device."""
        timestamp = datetime.now()
        filename = f"step_{step_index:03d}_{timestamp.strftime('%H%M%S_%f')}.png"
        output_path = output_dir / filename

        # Capture on device
        device_path = "/sdcard/yeytest_screenshot.png"
        self._adb_cmd("shell", "screencap", "-p", device_path)

        # Pull to local
        self._adb_cmd("pull", device_path, str(output_path))

        # Clean up device
        self._adb_cmd("shell", "rm", device_path)

        return Screenshot(
            path=output_path,
            timestamp=timestamp,
            step_index=step_index,
            description=description,
        )

    def start_screenrecord(self, output_path: Path, time_limit: int = 180) -> subprocess.Popen:
        """Start screen recording (max 3 min by default)."""
        device_path = "/sdcard/yeytest_recording.mp4"
        cmd = ["adb"]
        if self.device_id:
            cmd.extend(["-s", self.device_id])
        cmd.extend([
            "shell", "screenrecord",
            "--time-limit", str(time_limit),
            device_path
        ])
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stop_screenrecord(self, process: subprocess.Popen, output_path: Path) -> None:
        """Stop recording and pull video."""
        # Send interrupt to stop recording
        process.terminate()
        process.wait(timeout=5)

        # Give device time to finalize file
        import time
        time.sleep(1)

        # Pull video
        device_path = "/sdcard/yeytest_recording.mp4"
        self._adb_cmd("pull", device_path, str(output_path))
        self._adb_cmd("shell", "rm", device_path)

    def get_current_activity(self) -> str:
        """Get current foreground activity."""
        result = self._adb_cmd(
            "shell", "dumpsys", "activity", "activities",
            "|", "grep", "mResumedActivity"
        )
        return result.stdout.decode().strip()

    def is_device_ready(self) -> bool:
        """Check if device is ready."""
        try:
            devices = self.get_devices()
            if self.device_id:
                return self.device_id in devices
            return len(devices) > 0
        except ADBError:
            return False

