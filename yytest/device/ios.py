"""iOS Simulator wrapper for device interaction."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.models import Screenshot


class iOSError(Exception):
    """iOS command failed."""
    pass


class iOSDevice:
    """iOS Simulator interaction via xcrun simctl."""

    def __init__(self, device_id: Optional[str] = None):
        self.device_id = device_id
        self._validate_xcrun()

    def _validate_xcrun(self) -> None:
        """Check if xcrun is available."""
        try:
            subprocess.run(
                ["xcrun", "simctl", "list"],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError:
            raise iOSError("xcrun not found. Please install Xcode Command Line Tools.")
        except subprocess.CalledProcessError as e:
            raise iOSError(f"xcrun error: {e.stderr.decode()}")

    def _simctl_cmd(self, *args: str) -> subprocess.CompletedProcess:
        """Run simctl command."""
        cmd = ["xcrun", "simctl"]
        if self.device_id:
            cmd.extend(["-d", self.device_id])
        cmd.extend(args)
        
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise iOSError(f"simctl command failed: {result.stderr.decode()}")
        return result

    def get_devices(self) -> list[dict]:
        """List available iOS simulators."""
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "list", "devices", "available", "--json"],
                capture_output=True,
                check=True,
                text=True
            )
            import json
            data = json.loads(result.stdout)
            
            devices = []
            for runtime, sims in data.get("devices", {}).items():
                for sim in sims:
                    if sim.get("isAvailable", False):
                        devices.append({
                            "id": sim["udid"],
                            "name": sim["name"],
                            "runtime": runtime,
                            "state": sim.get("state", "Shutdown"),
                            "type": "ios"
                        })
            return devices
        except Exception as e:
            return []

    def get_booted_devices(self) -> list[str]:
        """List booted iOS simulators."""
        try:
            result = subprocess.run(
                ["xcrun", "simctl", "list", "devices", "booted"],
                capture_output=True,
                check=True,
                text=True
            )
            devices = []
            for line in result.stdout.split('\n'):
                if '(' in line and ')' in line:
                    # Extract UDID from line like "iPhone 15 Pro (12345-67890-ABCDEF)"
                    parts = line.split('(')
                    if len(parts) > 1:
                        udid = parts[1].split(')')[0].strip()
                        devices.append(udid)
            return devices
        except Exception:
            return []

    def screenshot(
        self,
        output_dir: Path,
        step_index: int,
        description: str = "",
    ) -> Screenshot:
        """Capture screenshot from iOS simulator."""
        timestamp = datetime.now()
        filename = f"step_{step_index:03d}_{timestamp.strftime('%H%M%S_%f')}.png"
        output_path = output_dir / filename

        # Use simctl io screenshot
        cmd = ["xcrun", "simctl", "io"]
        if self.device_id:
            cmd.extend([self.device_id])
        else:
            # Get first booted device
            booted = self.get_booted_devices()
            if not booted:
                raise iOSError("No booted iOS simulator found")
            cmd.extend([booted[0]])
        
        cmd.extend(["screenshot", str(output_path)])

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            raise iOSError(f"Screenshot failed: {result.stderr.decode()}")

        return Screenshot(
            path=output_path,
            timestamp=timestamp,
            step_index=step_index,
            description=description,
        )

    def boot_device(self, device_id: str) -> None:
        """Boot an iOS simulator."""
        subprocess.run(
            ["xcrun", "simctl", "boot", device_id],
            capture_output=True,
            check=True
        )

    def shutdown_device(self, device_id: str) -> None:
        """Shutdown an iOS simulator."""
        subprocess.run(
            ["xcrun", "simctl", "shutdown", device_id],
            capture_output=True
        )

    def is_device_ready(self) -> bool:
        """Check if device is ready."""
        try:
            if self.device_id:
                booted = self.get_booted_devices()
                return self.device_id in booted
            return len(self.get_booted_devices()) > 0
        except iOSError:
            return False

