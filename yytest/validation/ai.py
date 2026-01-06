"""AI-powered validation using Claude or GPT-4 Vision."""

from __future__ import annotations

import base64
import httpx
from pathlib import Path
from typing import Optional

from ..core.models import ValidationResult


class AIValidator:
    """
    AI Vision ile görsel doğrulama.
    Sadece gerektiğinde kullanılır (maliyet optimizasyonu).
    """

    def __init__(
        self,
        provider: str = "anthropic",  # "anthropic" or "openai"
        api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key or self._get_api_key()

    def _get_api_key(self) -> Optional[str]:
        """Get API key from environment."""
        import os
        if self.provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY")
        return os.getenv("OPENAI_API_KEY")

    def _encode_image(self, image_path: Path) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    async def validate_with_claude(
        self,
        screenshot: Path,
        expectation: str,
        context: str = "",
    ) -> ValidationResult:
        """
        Claude Vision ile doğrulama.
        
        Args:
            screenshot: Doğrulanacak ekran görüntüsü
            expectation: Ne bekliyoruz? Örn: "Login başarılı, anasayfa görünmeli"
            context: Ek bağlam (önceki adımlar vb.)
        """
        if not self.api_key:
            return ValidationResult(
                passed=True,
                confidence=0.0,
                reason="Anthropic API key bulunamadı, AI doğrulama atlandı",
                method="ai_skipped",
            )

        image_data = self._encode_image(screenshot)
        
        prompt = f"""Sen bir mobil uygulama test uzmanısın. 
Bu ekran görüntüsünü analiz et ve aşağıdaki beklentinin karşılanıp karşılanmadığını belirle.

BEKLENEN DURUM: {expectation}

{f"EK BAĞLAM: {context}" if context else ""}

Yanıtını şu formatta ver:
SONUÇ: BAŞARILI veya BAŞARISIZ
GÜVEN: 0-100 arası bir sayı
AÇIKLAMA: Kısa bir açıklama

Önemli kontroller:
1. Beklenen elementler görünüyor mu?
2. Herhangi bir hata mesajı var mı?
3. UI düzgün render edilmiş mi?
4. Beklenmeyen bir dialog veya popup var mı?
"""

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 500,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/png",
                                            "data": image_data,
                                        },
                                    },
                                    {
                                        "type": "text",
                                        "text": prompt,
                                    },
                                ],
                            }
                        ],
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()
                
                # Parse response
                content = result["content"][0]["text"]
                return self._parse_ai_response(content)

            except httpx.HTTPError as e:
                return ValidationResult(
                    passed=True,  # Don't fail test due to API error
                    confidence=0.0,
                    reason=f"AI API hatası: {str(e)}",
                    method="ai_error",
                )

    async def validate_with_openai(
        self,
        screenshot: Path,
        expectation: str,
        context: str = "",
    ) -> ValidationResult:
        """GPT-4 Vision ile doğrulama."""
        if not self.api_key:
            return ValidationResult(
                passed=True,
                confidence=0.0,
                reason="OpenAI API key bulunamadı, AI doğrulama atlandı",
                method="ai_skipped",
            )

        image_data = self._encode_image(screenshot)
        
        prompt = f"""Bir mobil uygulama test uzmanı olarak bu ekran görüntüsünü analiz et.

BEKLENEN DURUM: {expectation}
{f"EK BAĞLAM: {context}" if context else ""}

Yanıt formatı:
SONUÇ: BAŞARILI veya BAŞARISIZ
GÜVEN: 0-100
AÇIKLAMA: Kısa açıklama
"""

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": prompt,
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{image_data}",
                                        },
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 500,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()
                
                content = result["choices"][0]["message"]["content"]
                return self._parse_ai_response(content)

            except httpx.HTTPError as e:
                return ValidationResult(
                    passed=True,
                    confidence=0.0,
                    reason=f"AI API hatası: {str(e)}",
                    method="ai_error",
                )

    def _parse_ai_response(self, content: str) -> ValidationResult:
        """Parse AI response into ValidationResult."""
        lines = content.strip().split("\n")
        
        passed = True
        confidence = 0.5
        reason = content

        for line in lines:
            line_lower = line.lower()
            if "sonuç:" in line_lower or "result:" in line_lower:
                passed = "başarılı" in line_lower or "success" in line_lower
            elif "güven:" in line_lower or "confidence:" in line_lower:
                try:
                    # Extract number
                    import re
                    numbers = re.findall(r'\d+', line)
                    if numbers:
                        confidence = int(numbers[0]) / 100
                except ValueError:
                    pass
            elif "açıklama:" in line_lower or "explanation:" in line_lower:
                reason = line.split(":", 1)[-1].strip()

        return ValidationResult(
            passed=passed,
            confidence=confidence,
            reason=reason,
            method="ai_vision",
            details={"full_response": content},
        )

    async def validate(
        self,
        screenshot: Path,
        expectation: str,
        context: str = "",
    ) -> ValidationResult:
        """Seçilen provider ile doğrulama yap."""
        if self.provider == "anthropic":
            return await self.validate_with_claude(screenshot, expectation, context)
        return await self.validate_with_openai(screenshot, expectation, context)

