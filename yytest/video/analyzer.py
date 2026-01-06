"""Video analysis for post-test validation."""

from __future__ import annotations

import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Optional

import cv2
from PIL import Image

from ..core.models import ValidationResult
from ..validation.local import LocalValidator
from ..validation.ai import AIValidator


class VideoAnalyzer:
    """
    Test videosu analiz edici.
    
    Maestro testi bittikten sonra kaydedilen videoyu analiz eder:
    1. Key frame'leri çıkarır
    2. Her frame'i doğrular
    3. Anomali tespiti yapar
    """

    def __init__(
        self,
        local_validator: Optional[LocalValidator] = None,
        ai_validator: Optional[AIValidator] = None,
        frame_interval_ms: int = 500,  # Her 500ms'de bir frame
    ):
        self.local_validator = local_validator or LocalValidator()
        self.ai_validator = ai_validator
        self.frame_interval_ms = frame_interval_ms
        self._check_ffmpeg()

    def _check_ffmpeg(self) -> None:
        """Check if FFmpeg is available."""
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError:
            raise RuntimeError("FFmpeg not found. Install: brew install ffmpeg")

    def extract_frames(
        self,
        video_path: Path,
        output_dir: Optional[Path] = None,
        fps: float = 2.0,  # 2 frame per second
    ) -> list[Path]:
        """
        Videodan frame'leri çıkar.
        
        Args:
            video_path: Video dosyası
            output_dir: Frame'lerin kaydedileceği dizin
            fps: Saniyede kaç frame çıkarılacak
        
        Returns:
            Frame dosyalarının listesi
        """
        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp(prefix="yeytest_frames_"))
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract frames with FFmpeg
        output_pattern = str(output_dir / "frame_%04d.png")
        
        subprocess.run([
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            "-q:v", "2",
            output_pattern,
        ], capture_output=True, check=True)
        
        # Get sorted list of frames
        frames = sorted(output_dir.glob("frame_*.png"))
        return frames

    def detect_anomalies(
        self,
        frames: list[Path],
        threshold: float = 0.3,
    ) -> list[dict]:
        """
        Frame'lerde anomali tespit et.
        
        Anomaliler:
        - Ani ekran değişimleri (crash?)
        - Siyah ekran
        - Hata dialogları
        - Beklenmeyen UI değişimleri
        """
        anomalies = []
        prev_frame = None

        for i, frame_path in enumerate(frames):
            frame = cv2.imread(str(frame_path))
            
            if frame is None:
                continue

            # 1. Siyah ekran kontrolü
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_brightness = gray.mean()
            
            if mean_brightness < 10:  # Çok karanlık
                anomalies.append({
                    "type": "black_screen",
                    "frame_index": i,
                    "frame_path": frame_path,
                    "severity": "high",
                    "description": "Siyah ekran tespit edildi - crash olabilir",
                })

            # 2. Ani değişim kontrolü
            if prev_frame is not None:
                diff = cv2.absdiff(frame, prev_frame)
                diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                change_ratio = (diff_gray > 30).sum() / diff_gray.size

                if change_ratio > threshold:
                    anomalies.append({
                        "type": "sudden_change",
                        "frame_index": i,
                        "frame_path": frame_path,
                        "severity": "medium",
                        "change_ratio": change_ratio,
                        "description": f"Ani ekran değişimi (%{change_ratio*100:.1f})",
                    })

            # 3. Hata göstergeleri
            error_result = self.local_validator.detect_error_indicators(frame_path)
            if not error_result.passed:
                anomalies.append({
                    "type": "error_indicator",
                    "frame_index": i,
                    "frame_path": frame_path,
                    "severity": "high",
                    "description": error_result.reason,
                })

            prev_frame = frame

        return anomalies

    async def analyze_video(
        self,
        video_path: Path,
        expectations: list[str] = None,
        use_ai: bool = False,
    ) -> dict:
        """
        Tam video analizi yap.
        
        Args:
            video_path: Analiz edilecek video
            expectations: Test beklentileri
            use_ai: AI doğrulama kullanılsın mı
        
        Returns:
            Analiz sonuçları
        """
        # 1. Frame'leri çıkar
        frames = self.extract_frames(video_path)
        
        if not frames:
            return {
                "success": False,
                "error": "Video'dan frame çıkarılamadı",
            }

        # 2. Anomali tespiti
        anomalies = self.detect_anomalies(frames)

        # 3. AI analizi (opsiyonel)
        ai_insights = []
        if use_ai and self.ai_validator and expectations:
            # Sadece son frame'i analiz et (maliyet optimizasyonu)
            last_frame = frames[-1]
            
            result = await self.ai_validator.validate(
                screenshot=last_frame,
                expectation="; ".join(expectations),
                context="Bu test videosunun son frame'i",
            )
            ai_insights.append({
                "frame": "final",
                "result": result,
            })

        # 4. Sonuç
        has_critical = any(a["severity"] == "high" for a in anomalies)
        
        return {
            "success": not has_critical,
            "video_path": str(video_path),
            "total_frames": len(frames),
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "critical_anomalies": sum(1 for a in anomalies if a["severity"] == "high"),
            "ai_insights": ai_insights,
            "frames_dir": str(frames[0].parent) if frames else None,
        }

    def get_video_duration(self, video_path: Path) -> float:
        """Video süresini saniye olarak döndür."""
        result = subprocess.run([
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ], capture_output=True, text=True)
        
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0

    def extract_frame_at_time(
        self,
        video_path: Path,
        time_seconds: float,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Belirli bir zamandaki frame'i çıkar."""
        if output_path is None:
            output_path = Path(tempfile.mktemp(suffix=".png"))
        
        subprocess.run([
            "ffmpeg",
            "-ss", str(time_seconds),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path),
        ], capture_output=True, check=True)
        
        return output_path

