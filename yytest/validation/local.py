"""Local validation methods - FREE, no API costs."""

from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path
from PIL import Image
from typing import Optional

from ..core.models import ValidationResult


class LocalValidator:
    """
    Ücretsiz, lokal doğrulama metodları.
    
    1. Pixel Difference: İki screenshot arasındaki farkı hesaplar
    2. OCR: Ekranda beklenen text var mı kontrol eder
    3. Color Detection: Hata renkleri (kırmızı banner vb.) tespit eder
    4. Element Detection: Beklenen UI elementleri var mı
    """

    def __init__(self):
        self._tesseract_available = self._check_tesseract()

    def _check_tesseract(self) -> bool:
        """Check if Tesseract OCR is available."""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def pixel_difference(
        self,
        before: Path,
        after: Path,
        threshold: float = 0.01,
    ) -> ValidationResult:
        """
        İki screenshot arasındaki farkı hesapla.
        Eğer fark threshold'dan küçükse, hiçbir şey değişmemiş demektir.
        Bu genellikle kötü bir işaret - click çalışmamış olabilir.
        """
        img1 = cv2.imread(str(before))
        img2 = cv2.imread(str(after))

        if img1 is None or img2 is None:
            return ValidationResult(
                passed=False,
                confidence=0.0,
                reason="Screenshot okunamadı",
                method="pixel_diff",
            )

        # Resize if different sizes
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

        # Calculate difference
        diff = cv2.absdiff(img1, img2)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        
        # Calculate percentage of changed pixels
        non_zero = np.count_nonzero(diff_gray)
        total_pixels = diff_gray.shape[0] * diff_gray.shape[1]
        change_ratio = non_zero / total_pixels

        if change_ratio < threshold:
            return ValidationResult(
                passed=False,
                confidence=0.9,
                reason=f"Ekranda değişiklik yok ({change_ratio:.2%}). Aksiyon çalışmamış olabilir.",
                method="pixel_diff",
                details={"change_ratio": change_ratio},
            )

        return ValidationResult(
            passed=True,
            confidence=0.8,
            reason=f"Ekranda değişiklik tespit edildi ({change_ratio:.2%})",
            method="pixel_diff",
            details={"change_ratio": change_ratio},
        )

    def check_text_exists(
        self,
        screenshot: Path,
        expected_text: str,
        case_sensitive: bool = False,
    ) -> ValidationResult:
        """OCR ile ekranda beklenen text'i ara."""
        if not self._tesseract_available:
            return ValidationResult(
                passed=True,  # Skip validation
                confidence=0.0,
                reason="Tesseract OCR yüklü değil, text kontrolü atlandı",
                method="ocr",
            )

        import pytesseract
        
        img = Image.open(screenshot)
        text = pytesseract.image_to_string(img)

        if not case_sensitive:
            text = text.lower()
            expected_text = expected_text.lower()

        if expected_text in text:
            return ValidationResult(
                passed=True,
                confidence=0.85,
                reason=f"'{expected_text}' ekranda bulundu",
                method="ocr",
                details={"found_text": text[:500]},
            )

        return ValidationResult(
            passed=False,
            confidence=0.85,
            reason=f"'{expected_text}' ekranda bulunamadı",
            method="ocr",
            details={"found_text": text[:500]},
        )

    def detect_error_indicators(self, screenshot: Path) -> ValidationResult:
        """
        Hata göstergelerini tespit et:
        - Kırmızı renkli alanlar (error banner)
        - "error", "failed", "hata" gibi textler
        - Crash dialog'ları
        """
        img = cv2.imread(str(screenshot))
        if img is None:
            return ValidationResult(
                passed=True,
                confidence=0.0,
                reason="Screenshot okunamadı",
                method="error_detection",
            )

        # Convert to HSV for color detection
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Red color range (error indicators)
        lower_red1 = np.array([0, 100, 100])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([160, 100, 100])
        upper_red2 = np.array([180, 255, 255])

        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        red_mask = mask1 + mask2

        # Calculate red percentage
        red_pixels = np.count_nonzero(red_mask)
        total_pixels = red_mask.shape[0] * red_mask.shape[1]
        red_ratio = red_pixels / total_pixels

        # If significant red area detected, might be an error
        if red_ratio > 0.05:  # 5% or more red
            # Also check for error text via OCR
            if self._tesseract_available:
                import pytesseract
                text = pytesseract.image_to_string(Image.open(screenshot)).lower()
                error_words = ["error", "failed", "hata", "başarısız", "crash", "exception"]
                if any(word in text for word in error_words):
                    return ValidationResult(
                        passed=False,
                        confidence=0.9,
                        reason="Hata mesajı tespit edildi",
                        method="error_detection",
                        details={"red_ratio": red_ratio, "text_sample": text[:200]},
                    )

            return ValidationResult(
                passed=True,
                confidence=0.5,
                reason=f"Kırmızı alan tespit edildi (%{red_ratio:.1%}) ama hata texti yok",
                method="error_detection",
                details={"red_ratio": red_ratio},
            )

        return ValidationResult(
            passed=True,
            confidence=0.8,
            reason="Hata göstergesi tespit edilmedi",
            method="error_detection",
        )

    def validate_step(
        self,
        before: Optional[Path],
        after: Path,
        expected_text: Optional[str] = None,
    ) -> ValidationResult:
        """
        Bir adım için tam doğrulama yap.
        Birden fazla kontrolü birleştir.
        """
        results = []

        # 1. Pixel difference (eğer before varsa)
        if before:
            pixel_result = self.pixel_difference(before, after)
            results.append(pixel_result)
            if not pixel_result.passed:
                return pixel_result  # Hiç değişiklik yoksa hemen fail

        # 2. Error detection
        error_result = self.detect_error_indicators(after)
        results.append(error_result)
        if not error_result.passed:
            return error_result  # Hata varsa hemen fail

        # 3. Text check (eğer beklenti varsa)
        if expected_text:
            text_result = self.check_text_exists(after, expected_text)
            results.append(text_result)
            if not text_result.passed:
                return text_result

        # Hepsi geçtiyse
        avg_confidence = sum(r.confidence for r in results) / len(results) if results else 0.5
        return ValidationResult(
            passed=True,
            confidence=avg_confidence,
            reason="Tüm lokal doğrulamalar başarılı",
            method="local_combined",
            details={"checks_passed": len(results)},
        )

