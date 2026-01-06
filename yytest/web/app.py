"""yeytest Web UI - Full-featured dashboard for test management."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import uuid
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from ..nlp.parser import GroqParser
from ..device.adb import ADBDevice, ADBError
from ..device.ios import iOSDevice, iOSError

# Test storage
TESTS_DIR = Path("./yeytest_tests")
RESULTS_DIR = Path("./yeytest_results")

# Global test runner state
test_runs = {}


class YYTestHandler(SimpleHTTPRequestHandler):
    """Custom HTTP handler for yeytest web UI."""

    def do_GET(self):
        parsed = urlparse(self.path)
        
        routes = {
            "/": self.send_dashboard,
            "/index.html": self.send_dashboard,
            "/api/devices": self.send_devices,
            "/api/emulators": self.send_emulators,
            "/api/status": self.send_status,
            "/api/tests": self.send_tests,
            "/api/results": self.send_results,
            "/api/runs": self.send_runs,
        }
        
        handler = routes.get(parsed.path)
        if handler:
            handler()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        routes = {
            "/api/parse": self.handle_parse,
            "/api/run": self.handle_run,
            "/api/save-test": self.handle_save_test,
            "/api/run-suite": self.handle_run_suite,
            "/api/start-emulator": self.handle_start_emulator,
            "/api/self-heal": self.handle_self_heal,
        }
        
        handler = routes.get(parsed.path)
        if handler:
            handler(body)
        else:
            self.send_error(404)

    def send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))

    def send_devices(self):
        """Get connected devices."""
        try:
            adb = ADBDevice()
            devices = adb.get_devices()
            self.send_json({"devices": devices, "count": len(devices)})
        except ADBError as e:
            self.send_json({"devices": [], "error": str(e)}, 500)

    def send_emulators(self):
        """Get available emulators (Android AVDs + iOS Simulators)."""
        all_devices = []
        android_running = []
        ios_running = []
        
        # Android devices
        try:
            emulator_path = os.path.expanduser("~/Library/Android/sdk/emulator/emulator")
            result = subprocess.run(
                [emulator_path, "-list-avds"],
                capture_output=True, text=True
            )
            avds = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
            
            adb = ADBDevice()
            android_running = adb.get_devices()
            
            for avd in avds:
                is_running = any(avd.lower() in d.lower() or "emulator" in d for d in android_running)
                all_devices.append({
                    "id": f"android:{avd}",
                    "name": avd,
                    "platform": "android",
                    "running": is_running,
                    "type": "emulator"
                })
        except Exception:
            pass
        
        # iOS simulators
        try:
            ios = iOSDevice()
            ios_devices = ios.get_devices()
            ios_booted = ios.get_booted_devices()
            
            for device in ios_devices:
                is_running = device["id"] in ios_booted
                all_devices.append({
                    "id": f"ios:{device['id']}",
                    "name": device["name"],
                    "platform": "ios",
                    "running": is_running,
                    "type": "simulator",
                    "runtime": device.get("runtime", "")
                })
        except Exception:
            pass
        
        # Running devices (for compatibility)
        running = android_running + ios_running
        
        self.send_json({
            "devices": all_devices,
            "running": running,
            "android_count": len([d for d in all_devices if d["platform"] == "android"]),
            "ios_count": len([d for d in all_devices if d["platform"] == "ios"])
        })

    def send_status(self):
        """System status check."""
        status = {
            "adb": False,
            "maestro": False,
            "tesseract": False,
            "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
            "openai": bool(os.getenv("OPENAI_API_KEY")),
        }

        try:
            subprocess.run(["adb", "version"], capture_output=True, check=True)
            status["adb"] = True
        except:
            pass

        try:
            maestro_path = os.path.expanduser("~/.maestro/bin/maestro")
            subprocess.run([maestro_path, "--version"], capture_output=True, check=True)
            status["maestro"] = True
        except:
            pass

        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            status["tesseract"] = True
        except:
            pass

        self.send_json(status)

    def send_tests(self):
        """Get saved tests."""
        TESTS_DIR.mkdir(exist_ok=True)
        tests = []
        for f in TESTS_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                tests.append(data)
            except:
                pass
        self.send_json({"tests": tests})

    def send_results(self):
        """Get test results."""
        RESULTS_DIR.mkdir(exist_ok=True)
        results = []
        # Results are in subdirectories: yeytest_results/{run_id}/result.json
        for result_file in sorted(RESULTS_DIR.glob("*/result.json"), reverse=True)[:20]:
            try:
                data = json.loads(result_file.read_text())
                results.append(data)
            except:
                pass
        self.send_json({"results": results})

    def send_runs(self):
        """Get current test runs status."""
        self.send_json({"runs": list(test_runs.values())})

    def handle_parse(self, body: str):
        """Parse natural language to Maestro YAML."""
        try:
            data = json.loads(body)
            scenario = data.get("scenario", "")
            app_id = data.get("appId")

            parser = GroqParser(app_id=app_id)
            yaml_content, expectations = parser.parse_and_convert(scenario)

            self.send_json({
                "yaml": yaml_content,
                "expectations": expectations,
                "stepCount": len(expectations),
            })
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_save_test(self, body: str):
        """Save a test to disk."""
        try:
            data = json.loads(body)
            TESTS_DIR.mkdir(exist_ok=True)
            
            test_id = data.get("id") or str(uuid.uuid4())[:8]
            test_data = {
                "id": test_id,
                "name": data.get("name", f"Test {test_id}"),
                "appId": data.get("appId", ""),
                "scenario": data.get("scenario", ""),
                "yaml": data.get("yaml", ""),
                "expectations": data.get("expectations", []),
                "createdAt": datetime.now().isoformat(),
            }
            
            (TESTS_DIR / f"{test_id}.json").write_text(
                json.dumps(test_data, ensure_ascii=False, indent=2)
            )
            
            self.send_json({"success": True, "test": test_data})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_run(self, body: str):
        """Run a single test."""
        try:
            data = json.loads(body)
            yaml_content = data.get("yaml", "")
            device_id = data.get("deviceId")
            app_id = data.get("appId", "")
            test_name = data.get("name", "test")
            
            if not yaml_content:
                self.send_json({"error": "YAML içeriği gerekli"}, 400)
                return
            
            # Create run ID
            run_id = str(uuid.uuid4())[:8]
            
            # Start test in background
            thread = threading.Thread(
                target=run_test_background,
                args=(run_id, yaml_content, device_id, app_id, test_name)
            )
            thread.start()
            
            test_runs[run_id] = {
                "id": run_id,
                "name": test_name,
                "status": "running",
                "startedAt": datetime.now().isoformat(),
                "steps": [],
            }
            
            self.send_json({"success": True, "runId": run_id})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_run_suite(self, body: str):
        """Run multiple tests as a suite."""
        try:
            data = json.loads(body)
            test_ids = data.get("testIds", [])
            device_id = data.get("deviceId")
            
            if not test_ids:
                self.send_json({"error": "Test ID'leri gerekli"}, 400)
                return
            
            suite_id = str(uuid.uuid4())[:8]
            
            # Start suite in background
            thread = threading.Thread(
                target=run_suite_background,
                args=(suite_id, test_ids, device_id)
            )
            thread.start()
            
            test_runs[suite_id] = {
                "id": suite_id,
                "name": f"Suite ({len(test_ids)} test)",
                "status": "running",
                "type": "suite",
                "testIds": test_ids,
                "startedAt": datetime.now().isoformat(),
                "results": [],
            }
            
            self.send_json({"success": True, "suiteId": suite_id})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_start_emulator(self, body: str):
        """Start an emulator (Android or iOS)."""
        try:
            data = json.loads(body)
            device_id = data.get("id") or data.get("name")
            platform = data.get("platform", "android")
            
            if not device_id:
                self.send_json({"error": "Cihaz ID gerekli"}, 400)
                return
            
            if platform == "ios":
                # Extract actual device ID
                if device_id.startswith("ios:"):
                    device_id = device_id.replace("ios:", "")
                
                # Boot iOS simulator
                ios = iOSDevice()
                ios.boot_device(device_id)
                self.send_json({"success": True, "message": "iOS simulator başlatılıyor..."})
            else:
                # Android emulator
                if device_id.startswith("android:"):
                    avd_name = device_id.replace("android:", "")
                else:
                    avd_name = device_id
                
                emulator_path = os.path.expanduser("~/Library/Android/sdk/emulator/emulator")
                subprocess.Popen(
                    [emulator_path, "-avd", avd_name, "-no-snapshot-load"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.send_json({"success": True, "message": f"{avd_name} başlatılıyor..."})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_self_heal(self, body: str):
        """Start self-healing test run."""
        try:
            data = json.loads(body)
            yaml_content = data.get("yaml", "")
            device_id = data.get("deviceId", "")
            app_id = data.get("appId", "")
            test_name = data.get("testName", "Self-Healing Test")
            max_retries = data.get("maxRetries", 5)
            
            if not yaml_content:
                self.send_json({"error": "YAML içeriği gerekli"}, 400)
                return
            
            if not device_id:
                self.send_json({"error": "Cihaz seçimi gerekli"}, 400)
                return
            
            run_id = str(uuid.uuid4())[:8]
            
            # Background thread'de çalıştır
            thread = threading.Thread(
                target=run_self_healing_test_background,
                args=(run_id, yaml_content, device_id, app_id, test_name, max_retries),
                daemon=True
            )
            thread.start()
            
            self.send_json({
                "success": True,
                "runId": run_id,
                "message": "Self-healing test başlatıldı"
            })
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def send_dashboard(self):
        html = get_dashboard_html()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


def run_test_background(run_id: str, yaml_content: str, device_id: str, app_id: str, test_name: str):
    """Run test in background thread."""
    import tempfile
    import time
    
    try:
        # Create temp YAML file
        RESULTS_DIR.mkdir(exist_ok=True)
        test_dir = RESULTS_DIR / run_id
        test_dir.mkdir(exist_ok=True)
        
        yaml_file = test_dir / "test.yaml"
        yaml_file.write_text(yaml_content)
        
        # Detect platform from device_id
        platform = "android"
        actual_device_id = device_id
        if device_id.startswith("android:"):
            actual_device_id = device_id.replace("android:", "")
            platform = "android"
        elif device_id.startswith("ios:"):
            actual_device_id = device_id.replace("ios:", "")
            platform = "ios"
        
        # Initialize device objects
        ios_device = None
        adb = None
        if platform == "ios":
            ios_device = iOSDevice(actual_device_id)
        else:
            adb = ADBDevice(actual_device_id)
        
        # Take before screenshot
        try:
            if platform == "ios":
                before_shot = ios_device.screenshot(test_dir, 0, "before")
            else:
                before_shot = adb.screenshot(test_dir, 0, "before")
            test_runs[run_id]["beforeScreenshot"] = str(before_shot.path)
        except Exception as e:
            print(f"Screenshot error: {e}")
        
        # Run Maestro
        maestro_path = os.path.expanduser("~/.maestro/bin/maestro")
        cmd = [maestro_path, "test", str(yaml_file)]
        
        env = os.environ.copy()
        
        android_emulator_info = []  # (port, avd_name) tuples
        
        if platform == "ios" and actual_device_id:
            # iOS için: iOS simulator'ün booted olduğundan emin ol
            try:
                if ios_device is None:
                    ios_device = iOSDevice(actual_device_id)
                booted = ios_device.get_booted_devices()
                if actual_device_id not in booted:
                    print(f"Booting iOS simulator {actual_device_id}...")
                    ios_device.boot_device(actual_device_id)
                    import time
                    time.sleep(5)  # Boot için bekle
                
                # iOS için: Android emulator'leri geçici olarak kapat
                # (Maestro önce Android'i seçiyor, iOS için bunu önlemek lazım)
                try:
                    # Önce mevcut Android emulator'leri kontrol et
                    adb_check = subprocess.run(
                        ["adb", "devices"],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    android_count = sum(1 for line in adb_check.stdout.split('\n') if 'emulator' in line and 'device' in line)
                    print(f"Found {android_count} Android emulator(s) - closing for iOS test...")
                    
                    # AVD listesini al (emulator'leri tekrar başlatmak için)
                    emulator_path = os.path.expanduser("~/Library/Android/sdk/emulator/emulator")
                    avd_result = subprocess.run(
                        [emulator_path, "-list-avds"],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    avd_list = [line.strip() for line in avd_result.stdout.strip().split('\n') if line.strip()]
                    
                    # Tüm emulator process'lerini kapat (daha agresif)
                    kill_result = subprocess.run(
                        ["pkill", "-9", "-f", "emulator"],
                        capture_output=True,
                        timeout=2
                    )
                    print(f"Killed emulator processes (return code: {kill_result.returncode})")
                    
                    # ADB server'ı restart et
                    subprocess.run(
                        ["adb", "kill-server"],
                        capture_output=True,
                        timeout=2
                    )
                    import time
                    time.sleep(2)  # Daha uzun bekle
                    subprocess.run(
                        ["adb", "start-server"],
                        capture_output=True,
                        timeout=5
                    )
                    time.sleep(1)
                    
                    # Android emulator'lerin kapandığını doğrula
                    adb_verify = subprocess.run(
                        ["adb", "devices"],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    android_after = sum(1 for line in adb_verify.stdout.split('\n') if 'emulator' in line and 'device' in line)
                    print(f"Android emulators after close: {android_after} (should be 0)")
                    
                    # AVD bilgilerini kaydet (tekrar başlatmak için)
                    for avd in avd_list:
                        android_emulator_info.append(("unknown", avd))
                    
                    print(f"✅ Android emulator'ler kapatıldı ({len(avd_list)} AVD) - iOS test için hazır")
                except Exception as e:
                    print(f"❌ Could not stop Android: {e}")
                    import traceback
                    traceback.print_exc()
                    
            except Exception as e:
                print(f"iOS simulator setup error: {e}")
        
        # iOS için Android emulator'leri kapatıldıktan sonra biraz bekle
        if platform == "ios" and android_emulator_info:
            import time
            time.sleep(3)  # Android emulator'lerin tamamen kapanmasını bekle
        
        # Maestro testini çalıştır
        print(f"Running Maestro test on {platform} device: {actual_device_id}")
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
        
        # Android emulator'leri tekrar başlat (eğer kapatıldıysa)
        if android_emulator_info:
            import time
            time.sleep(2)  # Test bitmesini bekle
            for port, avd_name in android_emulator_info:
                try:
                    # Emulator'ü tekrar başlat
                    emulator_path = os.path.expanduser("~/Library/Android/sdk/emulator/emulator")
                    subprocess.Popen(
                        [emulator_path, "-avd", avd_name, "-no-snapshot-load"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print(f"Android emulator {avd_name} restarting...")
                except Exception as e:
                    print(f"Could not restart Android emulator: {e}")
        
        # Take after screenshot
        try:
            if platform == "ios":
                after_shot = ios_device.screenshot(test_dir, 1, "after")
            else:
                after_shot = adb.screenshot(test_dir, 1, "after")
            test_runs[run_id]["afterScreenshot"] = str(after_shot.path)
        except Exception as e:
            print(f"Screenshot error: {e}")
        
        # Parse result
        passed = result.returncode == 0
        steps = []
        for line in result.stdout.split('\n'):
            if 'COMPLETED' in line:
                steps.append({"action": line.strip(), "status": "passed"})
            elif 'FAILED' in line:
                steps.append({"action": line.strip(), "status": "failed"})
        
        # Update run status
        test_runs[run_id].update({
            "status": "passed" if passed else "failed",
            "finishedAt": datetime.now().isoformat(),
            "steps": steps,
            "output": result.stdout,
            "error": result.stderr if not passed else None,
        })
        
        # Save result
        result_data = test_runs[run_id].copy()
        result_data["yaml"] = yaml_content
        (test_dir / "result.json").write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2, default=str)
        )
        
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_trace = traceback.format_exc()
        print(f"❌ Test execution error: {error_msg}")
        print(error_trace)
        test_runs[run_id].update({
            "status": "error",
            "error": error_msg,
            "finishedAt": datetime.now().isoformat(),
        })
        # Result dosyasına da kaydet
        try:
            RESULTS_DIR.mkdir(exist_ok=True)
            test_dir = RESULTS_DIR / run_id
            test_dir.mkdir(exist_ok=True)
            result_data = test_runs[run_id].copy()
            (test_dir / "result.json").write_text(
                json.dumps(result_data, ensure_ascii=False, indent=2, default=str)
            )
        except:
            pass


def analyze_and_fix_test(yaml_content: str, error_log: str, app_id: str) -> str:
    """Analyze test failure and fix the YAML using AI."""
    try:
        parser = GroqParser(app_id=app_id)
        
        prompt = f"""Sen bir mobil test uzmanısın. Aşağıdaki Maestro test senaryosu başarısız oldu. Hata loglarını inceleyip test adımlarını düzelt.

MEVCUT TEST YAML:
{yaml_content}

HATA LOGLARI:
{error_log[:2000]}

Görevlerin:
1. Hata loglarını analiz et
2. Hangi adımın başarısız olduğunu belirle
3. Element selector'ları, bekleme süreleri, veya adım sırasını düzelt
4. Düzeltilmiş YAML'ı döndür

Sadece düzeltilmiş YAML'ı döndür, açıklama yapma. Yorum satırları ekle (# ile) hangi düzeltmelerin yapıldığını belirtmek için.
"""

        # Groq API ile düzeltilmiş YAML'ı al
        import subprocess as sp
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return yaml_content  # API key yoksa orijinal YAML'ı döndür
        
        cmd = [
            "curl", "-s", "-X", "POST", "https://api.groq.com/openai/v1/chat/completions",
            "-H", "Content-Type: application/json",
            "-H", f"Authorization: Bearer {api_key}",
            "-d", json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2000,
            })
        ]
        
        result = sp.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        response_json = json.loads(result.stdout)
        fixed_yaml = response_json["choices"][0]["message"]["content"]
        
        # Markdown code blocks'ları temizle
        fixed_yaml = fixed_yaml.replace("```yaml", "").replace("```", "").strip()
        
        return fixed_yaml
    except Exception as e:
        print(f"AI fix failed: {e}")
        return yaml_content  # Hata olursa orijinal YAML'ı döndür


def run_self_healing_test_background(run_id: str, yaml_content: str, device_id: str, app_id: str, test_name: str, max_retries: int = 5):
    """Run test with self-healing - automatically fix and retry on failure."""
    import time
    
    test_runs[run_id] = {
        "id": run_id,
        "name": test_name,
        "status": "running",
        "startedAt": datetime.now().isoformat(),
        "retries": [],
        "currentRetry": 0,
        "maxRetries": max_retries,
    }
    
    current_yaml = yaml_content
    retry_count = 0
    
    while retry_count < max_retries:
        retry_id = f"{run_id}_retry_{retry_count}"
        test_runs[run_id]["currentRetry"] = retry_count
        
        # Test çalıştır
        try:
            # Create temp YAML file
            RESULTS_DIR.mkdir(exist_ok=True)
            test_dir = RESULTS_DIR / retry_id
            test_dir.mkdir(exist_ok=True)
            
            yaml_file = test_dir / "test.yaml"
            yaml_file.write_text(current_yaml)
            
            # Detect platform
            platform = "android"
            actual_device_id = device_id
            if device_id.startswith("android:"):
                actual_device_id = device_id.replace("android:", "")
                platform = "android"
            elif device_id.startswith("ios:"):
                actual_device_id = device_id.replace("ios:", "")
                platform = "ios"
            
            # Initialize devices
            ios_device = None
            adb = None
            if platform == "ios":
                ios_device = iOSDevice(actual_device_id)
            else:
                adb = ADBDevice(actual_device_id)
            
            # Android emulator handling for iOS
            android_emulator_info = []
            if platform == "ios" and actual_device_id:
                try:
                    if ios_device is None:
                        ios_device = iOSDevice(actual_device_id)
                    booted = ios_device.get_booted_devices()
                    if actual_device_id not in booted:
                        ios_device.boot_device(actual_device_id)
                        time.sleep(5)
                    
                    # Close Android emulators
                    emulator_path = os.path.expanduser("~/Library/Android/sdk/emulator/emulator")
                    avd_result = subprocess.run(
                        [emulator_path, "-list-avds"],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    avd_list = [line.strip() for line in avd_result.stdout.strip().split('\n') if line.strip()]
                    
                    subprocess.run(["pkill", "-9", "-f", "emulator"], capture_output=True, timeout=2)
                    subprocess.run(["adb", "kill-server"], capture_output=True, timeout=2)
                    time.sleep(2)
                    subprocess.run(["adb", "start-server"], capture_output=True, timeout=5)
                    time.sleep(1)
                    
                    for avd in avd_list:
                        android_emulator_info.append(("unknown", avd))
                except Exception as e:
                    print(f"iOS setup error: {e}")
            
            if platform == "ios" and android_emulator_info:
                time.sleep(3)
            
            # Run Maestro
            maestro_path = os.path.expanduser("~/.maestro/bin/maestro")
            cmd = [maestro_path, "test", str(yaml_file)]
            env = os.environ.copy()
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
            
            # Restart Android emulators if needed
            if android_emulator_info:
                time.sleep(2)
                for port, avd_name in android_emulator_info:
                    try:
                        emulator_path = os.path.expanduser("~/Library/Android/sdk/emulator/emulator")
                        subprocess.Popen(
                            [emulator_path, "-avd", avd_name, "-no-snapshot-load"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                    except:
                        pass
            
            passed = result.returncode == 0
            
            retry_result = {
                "retry": retry_count,
                "status": "passed" if passed else "failed",
                "output": result.stdout,
                "error": result.stderr if not passed else None,
                "yaml": current_yaml,
            }
            
            test_runs[run_id]["retries"].append(retry_result)
            
            if passed:
                # Test başarılı!
                test_runs[run_id].update({
                    "status": "passed",
                    "finishedAt": datetime.now().isoformat(),
                    "finalYaml": current_yaml,
                })
                return
            
            # Test başarısız - AI ile düzelt
            if retry_count < max_retries - 1:
                error_log = result.stderr or result.stdout
                print(f"🔄 Retry {retry_count + 1}/{max_retries}: Analyzing failure and fixing...")
                fixed_yaml = analyze_and_fix_test(current_yaml, error_log, app_id)
                current_yaml = fixed_yaml
                retry_count += 1
                time.sleep(2)  # Kısa bir bekleme
            else:
                # Max retry'a ulaşıldı
                test_runs[run_id].update({
                    "status": "failed",
                    "finishedAt": datetime.now().isoformat(),
                    "finalYaml": current_yaml,
                })
                return
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"❌ Self-healing test error: {error_msg}")
            test_runs[run_id].update({
                "status": "error",
                "error": error_msg,
                "finishedAt": datetime.now().isoformat(),
            })
            return


def run_suite_background(suite_id: str, test_ids: list, device_id: str):
    """Run test suite in background."""
    results = []
    
    for test_id in test_ids:
        test_file = TESTS_DIR / f"{test_id}.json"
        if not test_file.exists():
            results.append({"testId": test_id, "status": "not_found"})
            continue
        
        test_data = json.loads(test_file.read_text())
        
        # Run individual test
        run_id = f"{suite_id}_{test_id}"
        run_test_background(
            run_id,
            test_data.get("yaml", ""),
            device_id,
            test_data.get("appId", ""),
            test_data.get("name", test_id)
        )
        
        # Wait for completion
        import time
        while test_runs.get(run_id, {}).get("status") == "running":
            time.sleep(0.5)
        
        results.append({
            "testId": test_id,
            "name": test_data.get("name"),
            "status": test_runs.get(run_id, {}).get("status", "unknown"),
        })
        
        test_runs[suite_id]["results"] = results
    
    # Update suite status
    all_passed = all(r.get("status") == "passed" for r in results)
    test_runs[suite_id].update({
        "status": "passed" if all_passed else "failed",
        "finishedAt": datetime.now().isoformat(),
        "results": results,
    })


def get_dashboard_html() -> str:
    return '''<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>yeytest - AI-Powered Visual Test Validation</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #151520;
            --bg-tertiary: #1e1e2e;
            --bg-card: #1a1a28;
            --bg-card-hover: #202030;
            --text-primary: #ffffff;
            --text-secondary: #b4b4c4;
            --text-muted: #6b6b7b;
            --accent: #8b5cf6;
            --accent-hover: #9d6ef7;
            --accent-glow: rgba(139, 92, 246, 0.2);
            --success: #10b981;
            --success-bg: rgba(16, 185, 129, 0.15);
            --error: #ef4444;
            --error-bg: rgba(239, 68, 68, 0.15);
            --warning: #f59e0b;
            --border: #2a2a3a;
            --border-hover: #3a3a4a;
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.4);
            --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.5);
            --radius-sm: 8px;
            --radius-md: 12px;
            --radius-lg: 16px;
        }

        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, var(--bg-primary) 0%, #0f0f1a 100%);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }

        .app {
            display: grid;
            grid-template-columns: 280px 1fr;
            min-height: 100vh;
        }

        /* Sidebar */
        .sidebar {
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            padding: 2rem 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 2.5rem;
            backdrop-filter: blur(10px);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border);
        }

        .logo-icon {
            width: 44px;
            height: 44px;
            background: linear-gradient(135deg, var(--accent) 0%, #ec4899 100%);
            border-radius: var(--radius-md);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            box-shadow: var(--shadow-md);
            transition: transform 0.3s ease;
        }

        .logo:hover .logo-icon {
            transform: scale(1.05) rotate(5deg);
        }

        .logo-text {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .nav-section {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .nav-title {
            font-size: 0.7rem;
            text-transform: uppercase;
            color: var(--text-muted);
            letter-spacing: 0.1em;
            margin-bottom: 0.75rem;
            font-weight: 600;
        }

        .nav-item {
            display: flex;
            align-items: center;
            gap: 0.875rem;
            padding: 0.875rem 1.125rem;
            border-radius: var(--radius-sm);
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            color: var(--text-secondary);
            font-size: 0.9375rem;
            position: relative;
        }

        .nav-item::before {
            content: '';
            position: absolute;
            left: 0;
            top: 50%;
            transform: translateY(-50%);
            width: 3px;
            height: 0;
            background: var(--accent);
            border-radius: 0 3px 3px 0;
            transition: height 0.25s ease;
        }

        .nav-item:hover {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            transform: translateX(4px);
        }

        .nav-item.active {
            background: linear-gradient(90deg, rgba(139, 92, 246, 0.15) 0%, transparent 100%);
            color: var(--text-primary);
            font-weight: 600;
        }

        .nav-item.active::before {
            height: 60%;
        }

        /* Header device selector */
        .header-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1.25rem 2.5rem;
            background: rgba(21, 21, 32, 0.8);
            backdrop-filter: blur(20px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: var(--shadow-sm);
        }

        .header-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.02em;
        }

        .device-selector {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.625rem 1.25rem;
            background: var(--bg-tertiary);
            border-radius: var(--radius-md);
            border: 1px solid var(--border);
            box-shadow: var(--shadow-sm);
            transition: all 0.25s ease;
        }

        .device-selector:hover {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        .device-selector label {
            font-size: 1rem;
            color: var(--text-secondary);
            white-space: nowrap;
        }

        .device-selector select {
            min-width: 220px;
            padding: 0.625rem 1rem;
            background: var(--bg-secondary);
            border: 1px solid transparent;
            border-radius: var(--radius-sm);
            color: var(--text-primary);
            font-size: 0.9375rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .device-selector select:hover {
            background: var(--bg-card);
        }

        .device-selector select:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        .start-emulator-btn {
            padding: 0.625rem 1rem;
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%);
            border: none;
            border-radius: var(--radius-sm);
            color: white;
            font-size: 0.875rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s ease;
            box-shadow: var(--shadow-sm);
        }

        .start-emulator-btn:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }

        .start-emulator-btn:active {
            transform: translateY(0);
        }

        /* Main content */
        .main {
            padding: 2.5rem;
            overflow-y: auto;
            background: transparent;
        }

        .page { display: none; }
        .page.active { display: block; }

        .page-header {
            margin-bottom: 2rem;
        }

        .page-title {
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .page-subtitle {
            color: var(--text-secondary);
        }

        /* Cards */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            margin-bottom: 2rem;
            box-shadow: var(--shadow-md);
            transition: all 0.3s ease;
            overflow: hidden;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-lg);
            border-color: var(--border-hover);
        }

        .card-header {
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: rgba(139, 92, 246, 0.05);
        }

        .card-title {
            font-weight: 700;
            font-size: 1.125rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: var(--text-primary);
        }

        .card-body {
            padding: 2rem;
        }

        /* Forms */
        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-label {
            display: block;
            font-size: 0.9375rem;
            color: var(--text-secondary);
            margin-bottom: 0.75rem;
            font-weight: 500;
        }

        .form-input, .form-textarea, .form-select {
            width: 100%;
            padding: 0.875rem 1.25rem;
            background: var(--bg-secondary);
            border: 1.5px solid var(--border);
            border-radius: var(--radius-sm);
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.9375rem;
            transition: all 0.25s ease;
        }

        .form-input:hover, .form-textarea:hover {
            border-color: var(--border-hover);
            background: var(--bg-tertiary);
        }

        .form-input:focus, .form-textarea:focus, .form-select:focus {
            outline: none;
            border-color: var(--accent);
            background: var(--bg-tertiary);
            box-shadow: 0 0 0 4px var(--accent-glow);
        }

        .form-textarea {
            min-height: 180px;
            resize: vertical;
            font-family: 'JetBrains Mono', monospace;
            line-height: 1.7;
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.625rem;
            padding: 0.875rem 1.75rem;
            border-radius: var(--radius-sm);
            font-family: inherit;
            font-size: 0.9375rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            border: none;
            position: relative;
            overflow: hidden;
        }

        .btn::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 0;
            height: 0;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.2);
            transform: translate(-50%, -50%);
            transition: width 0.6s, height 0.6s;
        }

        .btn:hover::before {
            width: 300px;
            height: 300px;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%);
            color: white;
            box-shadow: var(--shadow-sm);
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }

        .btn-primary:active {
            transform: translateY(0);
        }

        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1.5px solid var(--border);
        }

        .btn-secondary:hover {
            background: var(--bg-card);
            border-color: var(--border-hover);
            transform: translateY(-1px);
        }

        .btn-success {
            background: linear-gradient(135deg, var(--success) 0%, #059669 100%);
            color: white;
            box-shadow: var(--shadow-sm);
        }

        .btn-success:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }

        .btn-group {
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
            flex-wrap: wrap;
        }

        /* YAML output */
        .yaml-output {
            background: var(--bg-secondary);
            border: 1.5px solid var(--border);
            border-radius: var(--radius-md);
            padding: 1.5rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
            line-height: 1.8;
            white-space: pre-wrap;
            color: var(--success);
            max-height: 400px;
            overflow-y: auto;
            box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.3);
            position: relative;
        }

        .yaml-output::-webkit-scrollbar {
            width: 8px;
        }

        .yaml-output::-webkit-scrollbar-track {
            background: var(--bg-tertiary);
            border-radius: 4px;
        }

        .yaml-output::-webkit-scrollbar-thumb {
            background: var(--accent);
            border-radius: 4px;
        }

        .yaml-output::-webkit-scrollbar-thumb:hover {
            background: var(--accent-hover);
        }

        /* Test list */
        .test-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .test-item {
            display: flex;
            align-items: center;
            gap: 1.25rem;
            padding: 1.25rem 1.5rem;
            background: var(--bg-secondary);
            border: 1.5px solid var(--border);
            border-radius: var(--radius-md);
            cursor: pointer;
            transition: all 0.25s ease;
            box-shadow: var(--shadow-sm);
        }

        .test-item:hover {
            border-color: var(--accent);
            background: var(--bg-card);
            transform: translateX(4px);
            box-shadow: var(--shadow-md);
        }

        .test-item.selected {
            border-color: var(--accent);
            background: linear-gradient(90deg, rgba(139, 92, 246, 0.15) 0%, var(--bg-card) 100%);
            box-shadow: 0 0 0 3px var(--accent-glow);
        }

        .test-checkbox {
            width: 20px;
            height: 20px;
            accent-color: var(--accent);
        }

        .test-info {
            flex: 1;
        }

        .test-name {
            font-weight: 600;
            margin-bottom: 0.25rem;
        }

        .test-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
        }

        .test-actions {
            display: flex;
            gap: 0.5rem;
        }

        .test-actions .btn {
            padding: 0.5rem 0.75rem;
            font-size: 0.75rem;
        }

        /* Results */
        .result-item {
            padding: 1.5rem;
            background: var(--bg-card);
            border: 1.5px solid var(--border);
            border-radius: var(--radius-md);
            margin-bottom: 1rem;
            box-shadow: var(--shadow-sm);
            transition: all 0.25s ease;
        }

        .result-item:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
            border-color: var(--border-hover);
        }

        .result-header {
            display: flex;
            align-items: center;
            gap: 1.25rem;
            margin-bottom: 1rem;
        }

        .result-status {
            padding: 0.375rem 1rem;
            border-radius: 20px;
            font-size: 0.8125rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            box-shadow: var(--shadow-sm);
        }

        .result-status.passed {
            background: linear-gradient(135deg, var(--success) 0%, #059669 100%);
            color: white;
        }

        .result-status.failed {
            background: linear-gradient(135deg, var(--error) 0%, #dc2626 100%);
            color: white;
        }

        .result-status.running {
            background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%);
            color: white;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .result-name {
            font-weight: 700;
            font-size: 1.0625rem;
            color: var(--text-primary);
        }

        .result-time {
            font-size: 0.8125rem;
            color: var(--text-muted);
            margin-left: auto;
        }

        .result-steps {
            font-size: 0.875rem;
            color: var(--text-secondary);
            line-height: 1.8;
        }

        /* Grid layouts */
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 2rem;
        }

        @media (max-width: 1200px) {
            .grid-2 { grid-template-columns: 1fr; }
        }

        /* Status indicators */
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--error);
        }

        .status-dot.active {
            background: var(--success);
            box-shadow: 0 0 8px var(--success);
        }

        /* Empty state */
        .empty-state {
            text-align: center;
            padding: 4rem 2rem;
            color: var(--text-muted);
        }

        .empty-state-icon {
            font-size: 4rem;
            margin-bottom: 1.5rem;
            opacity: 0.5;
            animation: float 3s ease-in-out infinite;
        }

        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }

        /* Loading */
        .loading {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid var(--border);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* Toast notifications */
        .toast-container {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            z-index: 1000;
        }

        .toast {
            padding: 1rem 1.5rem;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-top: 0.5rem;
            animation: slideIn 0.3s ease;
        }

        .toast.success { border-color: var(--success); }
        .toast.error { border-color: var(--error); }

        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
    </style>
</head>
<body>
    <div class="app">
        <!-- Sidebar -->
        <aside class="sidebar">
            <div class="logo">
                <div class="logo-icon">🐬</div>
                <span class="logo-text">yeytest</span>
            </div>

            <nav class="nav-section">
                <div class="nav-title">Test</div>
                <div class="nav-item active" data-page="create">✏️ Test Oluştur</div>
                <div class="nav-item" data-page="tests">📋 Kayıtlı Testler</div>
                <div class="nav-item" data-page="suite">🚀 Toplu Koşum</div>
            </nav>

            <nav class="nav-section">
                <div class="nav-title">Sonuçlar</div>
                <div class="nav-item" data-page="results">📊 Test Sonuçları</div>
                <div class="nav-item" data-page="running">⏳ Çalışan Testler</div>
                <div class="nav-item" data-page="self-heal">🔧 Self-Healing Tests</div>
            </nav>

        </aside>

        <!-- Main Content -->
        <main class="main">
            <!-- Header Bar with Device Selector -->
            <div class="header-bar">
                <div class="header-title" id="page-title">Test Oluştur</div>
                <div class="device-selector">
                    <label>📱</label>
                    <select id="device-select">
                        <option value="">Cihaz yükleniyor...</option>
                    </select>
                    <button class="start-emulator-btn" onclick="showEmulatorDialog()">
                        ➕ Başlat
                    </button>
                </div>
            </div>
            <!-- Create Test Page -->
            <div class="page active" id="page-create" data-title="✏️ Test Oluştur">

                <div class="grid-2">
                    <div class="card">
                        <div class="card-header">
                            <span class="card-title">✍️ Senaryo</span>
                        </div>
                        <div class="card-body">
                            <div class="form-group">
                                <label class="form-label">Test Adı</label>
                                <input type="text" class="form-input" id="test-name" placeholder="Login Testi">
                            </div>
                            <div class="form-group">
                                <label class="form-label">App ID</label>
                                <input type="text" class="form-input" id="app-id" placeholder="com.example.app">
                            </div>
                            <div class="form-group">
                                <label class="form-label">Test Senaryosu</label>
                                <textarea class="form-textarea" id="scenario-input" placeholder="1. Uygulamayı aç
2. 'Email' alanına 'test@test.com' yaz
3. 'Şifre' alanına '123456' yaz
4. 'Giriş Yap' butonuna tıkla
5. 'Hoşgeldin' yazısı görünmeli"></textarea>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-primary" onclick="parseScenario()">
                                    🔄 Parse Et
                                </button>
                                <button class="btn btn-secondary" onclick="saveTest()">
                                    💾 Kaydet
                                </button>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <span class="card-title">📄 Maestro YAML</span>
                            <button class="btn btn-secondary" onclick="copyYaml()" style="padding: 0.5rem 0.75rem; font-size: 0.75rem;">
                                📋 Kopyala
                            </button>
                        </div>
                        <div class="card-body">
                            <div class="yaml-output" id="yaml-output">Senaryo yazıp "Parse Et" butonuna tıklayın</div>
                            <div id="expectations-list" style="margin-top: 1rem;"></div>
                            <div class="btn-group">
                                <button class="btn btn-success" onclick="runCurrentTest()">
                                    ▶️ Testi Çalıştır
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Saved Tests Page -->
            <div class="page" id="page-tests" data-title="📋 Kayıtlı Testler">

                <div class="card">
                    <div class="card-body">
                        <div class="test-list" id="saved-tests-list">
                            <div class="empty-state">
                                <div class="empty-state-icon">📋</div>
                                <p>Henüz kayıtlı test yok</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Suite Runner Page -->
            <div class="page" id="page-suite" data-title="🚀 Toplu Koşum">

                <div class="card">
                    <div class="card-header">
                        <span class="card-title">🚀 Test Seç</span>
                        <button class="btn btn-primary" onclick="runSelectedTests()">
                            ▶️ Seçilenleri Çalıştır
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="test-list" id="suite-tests-list">
                            <div class="empty-state">
                                <div class="empty-state-icon">📋</div>
                                <p>Henüz kayıtlı test yok</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Results Page -->
            <div class="page" id="page-results" data-title="📊 Test Sonuçları">

                <div class="card">
                    <div class="card-body">
                        <div id="results-list">
                            <div class="empty-state">
                                <div class="empty-state-icon">📊</div>
                                <p>Henüz test sonucu yok</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Running Tests Page -->
            <div class="page" id="page-running" data-title="⏳ Çalışan Testler">

                <div class="card">
                    <div class="card-body">
                        <div id="running-list">
                            <div class="empty-state">
                                <div class="empty-state-icon">⏳</div>
                                <p>Çalışan test yok</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="page" id="page-self-heal" data-title="🔧 Self-Healing Tests">

                <div class="card">
                    <div class="card-header">
                        <span class="card-title">🔧 Self-Healing Test Çalıştır</span>
                    </div>
                    <div class="card-body">
                        <div class="form-group">
                            <label class="form-label">Test YAML</label>
                            <textarea class="form-textarea" id="self-heal-yaml" placeholder="appId: com.example.app
---
- launchApp
- tapOn: &quot;Button&quot;"></textarea>
                        </div>
                        <div class="form-group">
                            <label class="form-label">App ID</label>
                            <input type="text" class="form-input" id="self-heal-app-id" placeholder="com.example.app">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Test Adı</label>
                            <input type="text" class="form-input" id="self-heal-test-name" placeholder="Self-Healing Test">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Max Retry Sayısı</label>
                            <input type="number" class="form-input" id="self-heal-max-retries" value="5" min="1" max="10">
                        </div>
                        <div class="btn-group">
                            <button class="btn btn-primary" onclick="startSelfHealingTest()">
                                🚀 Self-Healing Test Başlat
                            </button>
                        </div>
                    </div>
                </div>

                <div class="card" id="self-heal-status-card" style="display: none;">
                    <div class="card-header">
                        <span class="card-title">📊 Self-Healing Test Durumu</span>
                    </div>
                    <div class="card-body">
                        <div id="self-heal-status">
                            <div class="result-item">
                                <div class="result-header">
                                    <span class="result-status running" id="self-heal-status-badge">Çalışıyor...</span>
                                    <span class="result-name" id="self-heal-test-name-display"></span>
                                </div>
                                <div class="result-steps" id="self-heal-retries-list">
                                    <p>Test başlatılıyor...</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>

    <div class="toast-container" id="toast-container"></div>

    <script>
        let currentYaml = '';
        let currentExpectations = [];
        let savedTests = [];
        let selectedTestIds = new Set();

        // Initialize navigation and other features
        window.initApp = function() {
            // Navigation
            document.querySelectorAll('.nav-item').forEach(item => {
                item.addEventListener('click', () => {
                    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
                    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
                    
                    item.classList.add('active');
                    const pageId = 'page-' + item.dataset.page;
                    const page = document.getElementById(pageId);
                    if (page) {
                        page.classList.add('active');
                        
                        // Update header title
                        const titleEl = document.getElementById('page-title');
                        if (titleEl) {
                            titleEl.textContent = page.dataset.title || 'yeytest';
                        }
                        
                        // Load data for page
                        if (item.dataset.page === 'tests' || item.dataset.page === 'suite') {
                            loadSavedTests();
                        } else if (item.dataset.page === 'results') {
                            loadResults();
                        } else if (item.dataset.page === 'running') {
                            loadRunningTests();
                        }
                    }
                });
            });
        };

        // Toast notifications
        function showToast(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.textContent = message;
            document.getElementById('toast-container').appendChild(toast);
            setTimeout(() => toast.remove(), 3000);
        }

        // Load devices
        async function loadDevices() {
            try {
                const select = document.getElementById('device-select');
                if (!select) return; // Element not found yet
                
                const res = await fetch('/api/emulators');
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                const data = await res.json();
                
                select.innerHTML = '<option value="">-- Cihaz Seç --</option>';
                
                // Group by platform
                const androidDevices = [];
                const iosDevices = [];
                
                data.devices?.forEach(device => {
                    if (device.platform === 'android') {
                        androidDevices.push(device);
                    } else if (device.platform === 'ios') {
                        iosDevices.push(device);
                    }
                });
                
                // Android devices
                if (androidDevices.length > 0) {
                    const androidGroup = document.createElement('optgroup');
                    androidGroup.label = '🤖 Android';
                    select.appendChild(androidGroup);
                    
                    androidDevices.forEach(device => {
                        const opt = document.createElement('option');
                        opt.value = device.id;
                        const icon = device.running ? '✅' : '📱';
                        opt.textContent = `${icon} ${device.name}`;
                        androidGroup.appendChild(opt);
                    });
                }
                
                // iOS devices
                if (iosDevices.length > 0) {
                    const iosGroup = document.createElement('optgroup');
                    iosGroup.label = '🍎 iOS';
                    select.appendChild(iosGroup);
                    
                    iosDevices.forEach(device => {
                        const opt = document.createElement('option');
                        opt.value = device.id;
                        const icon = device.running ? '✅' : '📱';
                        opt.textContent = `${icon} ${device.name}`;
                        iosGroup.appendChild(opt);
                    });
                }
            } catch (e) {
                console.error('Failed to load devices:', e);
                const select = document.getElementById('device-select');
                if (select) {
                    select.innerHTML = '<option value="">❌ Cihaz yüklenemedi</option>';
                }
            }
        }

        // Show emulator dialog
        function showEmulatorDialog() {
            const select = document.getElementById('device-select');
            const selected = select.value;
            
            if (!selected) {
                alert('Lütfen başlatılacak bir cihaz seçin');
                return;
            }
            
            // Get device info from option
            const option = select.options[select.selectedIndex];
            const deviceName = option.textContent.replace(/^[✅📱] /, '');
            const platform = selected.startsWith('ios:') ? 'ios' : 'android';
            
            if (confirm(`"${deviceName}" ${platform === 'ios' ? 'simulator' : 'emülatör'}ünü başlatmak istiyor musunuz?`)) {
                startEmulator(selected, platform);
            }
        }

        async function startEmulator(deviceId, platform) {
            try {
                const res = await fetch('/api/start-emulator', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: deviceId, platform })
                });
                const data = await res.json();
                showToast(data.message || 'Cihaz başlatılıyor...', 'success');
                
                // Refresh devices after a delay
                setTimeout(loadDevices, 5000);
            } catch (e) {
                showToast('Cihaz başlatılamadı', 'error');
            }
        }

        // Parse scenario
        async function parseScenario() {
            const scenario = document.getElementById('scenario-input').value;
            const appId = document.getElementById('app-id').value;
            
            if (!scenario.trim()) {
                showToast('Lütfen bir senaryo yazın', 'error');
                return;
            }

            try {
                const res = await fetch('/api/parse', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scenario, appId })
                });
                const data = await res.json();
                
                currentYaml = data.yaml;
                currentExpectations = data.expectations;
                
                document.getElementById('yaml-output').textContent = data.yaml;
                
                const expList = document.getElementById('expectations-list');
                expList.innerHTML = data.expectations.map((exp, i) => `
                    <div style="display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem; background: var(--bg-secondary); border-radius: 6px; margin-bottom: 0.25rem; font-size: 0.8rem;">
                        <span style="background: var(--accent); color: white; padding: 0.125rem 0.5rem; border-radius: 4px; font-size: 0.7rem;">${i + 1}</span>
                        ${exp}
                    </div>
                `).join('');
                
                showToast('Parse başarılı!', 'success');
            } catch (e) {
                showToast('Parse hatası: ' + e.message, 'error');
            }
        }

        // Copy YAML
        function copyYaml() {
            if (currentYaml) {
                navigator.clipboard.writeText(currentYaml);
                showToast('YAML kopyalandı!', 'success');
            }
        }

        // Save test
        async function saveTest() {
            const name = document.getElementById('test-name').value || 'Test ' + Date.now();
            const appId = document.getElementById('app-id').value;
            const scenario = document.getElementById('scenario-input').value;
            
            if (!currentYaml) {
                showToast('Önce senaryoyu parse edin', 'error');
                return;
            }

            try {
                const res = await fetch('/api/save-test', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        appId,
                        scenario,
                        yaml: currentYaml,
                        expectations: currentExpectations
                    })
                });
                const data = await res.json();
                
                if (data.success) {
                    showToast('Test kaydedildi!', 'success');
                } else {
                    showToast('Kaydetme hatası', 'error');
                }
            } catch (e) {
                showToast('Kaydetme hatası: ' + e.message, 'error');
            }
        }

        // Run current test
        async function runCurrentTest() {
            if (!currentYaml) {
                showToast('Önce senaryoyu parse edin', 'error');
                return;
            }

            const deviceId = document.getElementById('device-select').value;
            if (!deviceId) {
                showToast('Lütfen bir cihaz seçin', 'error');
                return;
            }

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        yaml: currentYaml,
                        deviceId,
                        appId: document.getElementById('app-id').value,
                        name: document.getElementById('test-name').value || 'Test'
                    })
                });
                const data = await res.json();
                
                if (data.success) {
                    showToast('Test başlatıldı! ID: ' + data.runId, 'success');
                    // Switch to running page
                    document.querySelector('[data-page="running"]').click();
                }
            } catch (e) {
                showToast('Test başlatılamadı: ' + e.message, 'error');
            }
        }

        // Load saved tests
        async function loadSavedTests() {
            try {
                const res = await fetch('/api/tests');
                const data = await res.json();
                savedTests = data.tests || [];
                
                renderTestsList('saved-tests-list', false);
                renderTestsList('suite-tests-list', true);
            } catch (e) {
                console.error('Failed to load tests:', e);
            }
        }

        function renderTestsList(containerId, showCheckbox) {
            const container = document.getElementById(containerId);
            
            if (savedTests.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📋</div>
                        <p>Henüz kayıtlı test yok</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = savedTests.map(test => `
                <div class="test-item ${selectedTestIds.has(test.id) ? 'selected' : ''}" data-id="${test.id}">
                    ${showCheckbox ? `
                        <input type="checkbox" class="test-checkbox" 
                            ${selectedTestIds.has(test.id) ? 'checked' : ''}
                            onchange="toggleTestSelection('${test.id}')">
                    ` : ''}
                    <div class="test-info">
                        <div class="test-name">${test.name}</div>
                        <div class="test-meta">
                            ${test.appId ? `📱 ${test.appId} • ` : ''}
                            ${test.expectations?.length || 0} adım
                        </div>
                    </div>
                    <div class="test-actions">
                        <button class="btn btn-secondary" onclick="loadTest('${test.id}')">📝 Düzenle</button>
                        <button class="btn btn-primary" onclick="runSavedTest('${test.id}')">▶️ Çalıştır</button>
                    </div>
                </div>
            `).join('');
        }

        function toggleTestSelection(id) {
            if (selectedTestIds.has(id)) {
                selectedTestIds.delete(id);
            } else {
                selectedTestIds.add(id);
            }
            renderTestsList('suite-tests-list', true);
        }

        async function loadTest(id) {
            const test = savedTests.find(t => t.id === id);
            if (test) {
                document.getElementById('test-name').value = test.name || '';
                document.getElementById('app-id').value = test.appId || '';
                document.getElementById('scenario-input').value = test.scenario || '';
                currentYaml = test.yaml || '';
                currentExpectations = test.expectations || [];
                
                document.getElementById('yaml-output').textContent = currentYaml;
                
                // Switch to create page
                document.querySelector('[data-page="create"]').click();
                showToast('Test yüklendi', 'success');
            }
        }

        async function runSavedTest(id) {
            const test = savedTests.find(t => t.id === id);
            if (!test) return;

            const deviceId = document.getElementById('device-select').value;
            if (!deviceId) {
                showToast('Lütfen bir cihaz seçin', 'error');
                return;
            }

            try {
                const res = await fetch('/api/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        yaml: test.yaml,
                        deviceId,
                        appId: test.appId,
                        name: test.name
                    })
                });
                const data = await res.json();
                
                if (data.success) {
                    showToast('Test başlatıldı!', 'success');
                    document.querySelector('[data-page="running"]').click();
                }
            } catch (e) {
                showToast('Test başlatılamadı', 'error');
            }
        }

        async function runSelectedTests() {
            if (selectedTestIds.size === 0) {
                showToast('Lütfen en az bir test seçin', 'error');
                return;
            }

            const deviceId = document.getElementById('device-select').value;
            if (!deviceId) {
                showToast('Lütfen bir cihaz seçin', 'error');
                return;
            }

            try {
                const res = await fetch('/api/run-suite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        testIds: Array.from(selectedTestIds),
                        deviceId
                    })
                });
                const data = await res.json();
                
                if (data.success) {
                    showToast(`Suite başlatıldı! ${selectedTestIds.size} test`, 'success');
                    document.querySelector('[data-page="running"]').click();
                }
            } catch (e) {
                showToast('Suite başlatılamadı', 'error');
            }
        }

        // Load results
        async function loadResults() {
            try {
                const res = await fetch('/api/results');
                const data = await res.json();
                
                const container = document.getElementById('results-list');
                const results = data.results || [];
                
                if (results.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">📊</div>
                            <p>Henüz test sonucu yok</p>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = results.map(r => `
                    <div class="result-item">
                        <div class="result-header">
                            <span class="result-status ${r.status}">${r.status === 'passed' ? '✅ PASS' : '❌ FAIL'}</span>
                            <span class="result-name">${r.name || 'Test'}</span>
                            <span class="result-time">${new Date(r.finishedAt).toLocaleString('tr-TR')}</span>
                            ${r.status === 'failed' && r.yaml ? `
                                <button class="btn btn-secondary" style="margin-left: auto; padding: 0.5rem 1rem; font-size: 0.875rem;" 
                                        onclick="autoFixTest('${r.id}', ${JSON.stringify(r.yaml).replace(/'/g, "\\'")}, ${JSON.stringify(r.appId || '').replace(/'/g, "\\'")})">
                                    🔧 Auto-Fix
                                </button>
                            ` : ''}
                        </div>
                        <div class="result-steps">
                            ${(r.steps || []).map(s => `${s.status === 'passed' ? '✅' : '❌'} ${s.action}`).join('<br>')}
                        </div>
                        ${r.error ? `<div style="margin-top: 0.5rem; color: var(--error); font-size: 0.875rem;">${r.error.substring(0, 200)}...</div>` : ''}
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to load results:', e);
            }
        }

        // Load running tests
        // Self-healing test functions
        let selfHealRunId = null;
        let selfHealInterval = null;

        async function autoFixTest(resultId, yaml, appId) {
            // Navigate to self-healing page and fill form
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            
            document.querySelector('[data-page="self-heal"]').classList.add('active');
            document.getElementById('page-self-heal').classList.add('active');
            
            document.getElementById('self-heal-yaml').value = yaml;
            document.getElementById('self-heal-app-id').value = appId;
            document.getElementById('self-heal-test-name').value = 'Auto-Fixed Test';
            
            showToast('Form dolduruldu, testi başlatabilirsin', 'info');
        }

        async function startSelfHealingTest() {
            const yaml = document.getElementById('self-heal-yaml').value.trim();
            const appId = document.getElementById('self-heal-app-id').value.trim();
            const testName = document.getElementById('self-heal-test-name').value.trim() || 'Self-Healing Test';
            const maxRetries = parseInt(document.getElementById('self-heal-max-retries').value) || 5;
            const deviceId = document.getElementById('device-select').value;

            if (!yaml) {
                showToast('YAML içeriği gerekli', 'error');
                return;
            }

            if (!deviceId) {
                showToast('Cihaz seçimi gerekli', 'error');
                return;
            }

            try {
                const res = await fetch('/api/self-heal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        yaml: yaml,
                        appId: appId,
                        testName: testName,
                        deviceId: deviceId,
                        maxRetries: maxRetries
                    })
                });

                const data = await res.json();
                if (data.error) {
                    showToast(data.error, 'error');
                    return;
                }

                selfHealRunId = data.runId;
                document.getElementById('self-heal-status-card').style.display = 'block';
                document.getElementById('self-heal-test-name-display').textContent = testName;
                showToast('Self-healing test başlatıldı', 'success');

                // Start polling for status
                if (selfHealInterval) clearInterval(selfHealInterval);
                selfHealInterval = setInterval(updateSelfHealStatus, 2000);
                updateSelfHealStatus();
            } catch (e) {
                showToast('Hata: ' + e.message, 'error');
            }
        }

        async function updateSelfHealStatus() {
            if (!selfHealRunId) return;

            try {
                const res = await fetch('/api/runs');
                const data = await res.json();
                const run = data.runs?.find(r => r.id === selfHealRunId);

                if (!run) {
                    if (selfHealInterval) clearInterval(selfHealInterval);
                    return;
                }

                const statusBadge = document.getElementById('self-heal-status-badge');
                const retriesList = document.getElementById('self-heal-retries-list');

                // Update status badge
                statusBadge.className = 'result-status ' + run.status;
                statusBadge.textContent = run.status === 'running' ? 'Çalışıyor...' : 
                                         run.status === 'passed' ? 'BAŞARILI' : 
                                         run.status === 'failed' ? 'BAŞARISIZ' : 'HATA';

                // Update retries list
                if (run.retries && run.retries.length > 0) {
                    retriesList.innerHTML = `
                        <div style="margin-bottom: 1rem;">
                            <strong>Retry ${run.currentRetry + 1} / ${run.maxRetries}</strong>
                        </div>
                        ${run.retries.map((retry, idx) => `
                            <div class="result-item" style="margin-bottom: 0.5rem; padding: 0.75rem;">
                                <div class="result-header">
                                    <span class="result-status ${retry.status}">${retry.status === 'passed' ? '✅ PASSED' : '❌ FAILED'}</span>
                                    <span>Retry ${retry.retry + 1}</span>
                                </div>
                                ${retry.error ? `<div style="margin-top: 0.5rem; font-size: 0.8rem; color: var(--text-muted);">${retry.error.substring(0, 200)}...</div>` : ''}
                            </div>
                        `).join('')}
                    `;
                } else {
                    retriesList.innerHTML = '<p>Test başlatılıyor...</p>';
                }

                // Stop polling if test is finished
                if (run.status !== 'running') {
                    if (selfHealInterval) clearInterval(selfHealInterval);
                    selfHealInterval = null;
                    
                    if (run.status === 'passed') {
                        showToast('Self-healing test başarılı!', 'success');
                    } else if (run.status === 'failed') {
                        showToast('Self-healing test başarısız (max retry)', 'error');
                    }
                }
            } catch (e) {
                console.error('Status update error:', e);
            }
        }

        async function loadRunningTests() {
            try {
                const res = await fetch('/api/runs');
                const data = await res.json();
                
                const container = document.getElementById('running-list');
                const runs = Object.values(data.runs || {}).filter(r => r.status === 'running');
                
                if (runs.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-state-icon">⏳</div>
                            <p>Çalışan test yok</p>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = runs.map(r => `
                    <div class="result-item">
                        <div class="result-header">
                            <span class="result-status running"><span class="loading"></span> Çalışıyor</span>
                            <span class="result-name">${r.name || 'Test'}</span>
                            <span class="result-time">${new Date(r.startedAt).toLocaleString('tr-TR')}</span>
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Failed to load running tests:', e);
            }
        }

        // Initialize on DOM ready
        function initializeApp() {
            window.initApp();
            loadDevices();
            setInterval(loadDevices, 10000);
            setInterval(() => {
                const runningPage = document.getElementById('page-running');
                if (runningPage && runningPage.classList.contains('active')) {
                    loadRunningTests();
                }
                const selfHealPage = document.getElementById('page-self-heal');
                if (selfHealPage && selfHealPage.classList.contains('active') && selfHealRunId) {
                    updateSelfHealStatus();
                }
            }, 2000);
        }

        // Run when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initializeApp);
        } else {
            initializeApp();
        }
    </script>
</body>
</html>'''


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Start the web server."""
    server = HTTPServer((host, port), YYTestHandler)
    print(f"🐬 yeytest Web UI running at http://{host}:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
        server.shutdown()


if __name__ == "__main__":
    run_server()
