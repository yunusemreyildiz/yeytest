"""Natural language to Maestro YAML converter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import yaml


@dataclass
class ParsedStep:
    action: str
    target: Optional[str] = None
    value: Optional[str] = None
    expectation: Optional[str] = None


class NLPParser:
    """
    Doğal dil test senaryolarını Maestro YAML formatına dönüştürür.
    
    Örnek giriş:
        1. Uygulamayı aç
        2. "Email" alanına "test@test.com" yaz
        3. "Login" butonuna tıkla
        4. "Hoşgeldin" yazısı görünmeli
    
    Çıktı: Maestro YAML
    """

    # Action patterns (Türkçe ve İngilizce)
    PATTERNS = {
        "launch": [
            r"uygulamayı aç",
            r"uygulamayı başlat",
            r"launch app",
            r"open app",
            r"start app",
        ],
        "tap": [
            r"[\"'](.+?)[\"']\s*(?:butonuna|düğmesine)?\s*(?:tıkla|bas|dokun)",
            r"(?:tıkla|bas|dokun)\s*[\"'](.+?)[\"']",
            r"tap\s*(?:on)?\s*[\"'](.+?)[\"']",
            r"click\s*(?:on)?\s*[\"'](.+?)[\"']",
            r"press\s*[\"'](.+?)[\"']",
        ],
        "input": [
            r"[\"'](.+?)[\"']\s*(?:alanına|kutusuna|yerine)\s*[\"'](.+?)[\"']\s*(?:yaz|gir|doldur)",
            r"(?:yaz|gir|doldur)\s*[\"'](.+?)[\"']\s*(?:alanına|içine)?\s*[\"'](.+?)[\"']",
            r"type\s*[\"'](.+?)[\"']\s*(?:in|into)?\s*[\"'](.+?)[\"']",
            r"enter\s*[\"'](.+?)[\"']\s*(?:in|into)?\s*[\"'](.+?)[\"']",
            r"input\s*[\"'](.+?)[\"']\s*(?:in|into)?\s*[\"'](.+?)[\"']",
        ],
        "assert_visible": [
            r"[\"'](.+?)[\"']\s*(?:yazısı|metni|texti)?\s*(?:görünmeli|görünsün|var mı|olmalı)",
            r"(?:görünmeli|görünsün|olmalı)\s*[\"'](.+?)[\"']",
            r"(?:see|verify|check|assert)\s*[\"'](.+?)[\"']",
            r"[\"'](.+?)[\"']\s*(?:should be|is|must be)\s*visible",
        ],
        "scroll": [
            r"(?:aşağı|yukarı|sola|sağa)\s*(?:kaydır|scroll)",
            r"scroll\s*(?:up|down|left|right)",
            r"(?:kaydır|scroll)",
        ],
        "wait": [
            r"(\d+)\s*(?:saniye|sn|s)\s*(?:bekle|dur)",
            r"wait\s*(\d+)\s*(?:seconds?|s)?",
            r"bekle\s*(\d+)",
        ],
        "back": [
            r"geri\s*(?:git|dön|bas)",
            r"go\s*back",
            r"press\s*back",
            r"navigate\s*back",
        ],
    }

    def __init__(self, app_id: Optional[str] = None):
        self.app_id = app_id

    def parse_step(self, text: str) -> Optional[ParsedStep]:
        """Tek bir adımı parse et."""
        text = text.strip().lower()
        
        # Numara varsa kaldır
        text = re.sub(r"^\d+[\.\)\-]\s*", "", text)

        # Launch
        for pattern in self.PATTERNS["launch"]:
            if re.search(pattern, text, re.IGNORECASE):
                return ParsedStep(action="launchApp")

        # Tap
        for pattern in self.PATTERNS["tap"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                target = match.group(1)
                return ParsedStep(action="tapOn", target=target)

        # Input (daha karmaşık - field ve value çıkar)
        for pattern in self.PATTERNS["input"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    # Hangisi field hangisi value? Bağlama göre
                    field, value = groups[0], groups[1]
                    return ParsedStep(action="inputText", target=field, value=value)

        # Assert visible
        for pattern in self.PATTERNS["assert_visible"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                target = match.group(1)
                return ParsedStep(
                    action="assertVisible",
                    target=target,
                    expectation=f"'{target}' görünür olmalı",
                )

        # Scroll
        for pattern in self.PATTERNS["scroll"]:
            if re.search(pattern, text, re.IGNORECASE):
                direction = "DOWN"  # Default
                if "yukarı" in text or "up" in text:
                    direction = "UP"
                elif "sol" in text or "left" in text:
                    direction = "LEFT"
                elif "sağ" in text or "right" in text:
                    direction = "RIGHT"
                return ParsedStep(action="scroll", value=direction)

        # Wait
        for pattern in self.PATTERNS["wait"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                seconds = match.group(1)
                return ParsedStep(action="wait", value=seconds)

        # Back
        for pattern in self.PATTERNS["back"]:
            if re.search(pattern, text, re.IGNORECASE):
                return ParsedStep(action="pressBack")

        return None

    def parse_scenario(self, text: str) -> list[ParsedStep]:
        """Çok satırlı veya virgülle ayrılmış senaryoyu parse et."""
        # Önce satırlara ayır
        lines = text.strip().split("\n")
        
        # Her satırı virgülle de ayır
        all_parts = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Virgülle ayrılmış parçaları da ekle
            parts = [p.strip() for p in line.split(",") if p.strip()]
            all_parts.extend(parts)
        
        steps = []
        for part in all_parts:
            step = self.parse_step(part)
            if step:
                steps.append(step)

        return steps

    def to_maestro_yaml(self, steps: list[ParsedStep]) -> str:
        """ParsedStep'leri Maestro YAML'a dönüştür."""
        flow = []
        
        for step in steps:
            if step.action == "launchApp":
                flow.append("launchApp")
            
            elif step.action == "tapOn":
                flow.append({"tapOn": step.target})
            
            elif step.action == "inputText":
                # Önce alana tıkla, sonra yaz
                if step.target:
                    flow.append({"tapOn": step.target})
                flow.append({"inputText": step.value})
            
            elif step.action == "assertVisible":
                flow.append({"assertVisible": step.target})
            
            elif step.action == "scroll":
                # Maestro uses just "scroll" for down, or swipe for direction
                if step.value and step.value.upper() != "DOWN":
                    flow.append({
                        "swipe": {
                            "direction": step.value.upper(),
                            "duration": 500
                        }
                    })
                else:
                    flow.append("scroll")
            
            elif step.action == "wait":
                flow.append({"wait": {"seconds": int(step.value)}})
            
            elif step.action == "pressBack":
                flow.append("pressBack")

        # Build YAML
        yaml_content = ""
        if self.app_id:
            yaml_content = f"appId: {self.app_id}\n---\n"
        
        yaml_content += yaml.dump(flow, default_flow_style=False, allow_unicode=True)
        return yaml_content

    def parse_and_convert(self, text: str) -> tuple[str, list[str]]:
        """
        Doğal dil senaryosunu parse et ve Maestro YAML'a dönüştür.
        
        Returns:
            (yaml_content, expectations): YAML ve beklentiler listesi
        """
        steps = self.parse_scenario(text)
        yaml_content = self.to_maestro_yaml(steps)
        expectations = [step.expectation or f"{step.action} başarılı" for step in steps]
        
        return yaml_content, expectations


def load_env():
    """Load .env file into environment."""
    import os
    env_file = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


class GroqParser(NLPParser):
    """
    Groq AI destekli parser - Llama 3.3 70B modeli.
    Ücretsiz, hızlı ve güçlü!
    """

    def __init__(self, app_id: Optional[str] = None):
        super().__init__(app_id)
        load_env()
        import os
        self._api_key = os.getenv("GROQ_API_KEY")

    def parse_with_groq(self, text: str) -> tuple[str, list[str]]:
        """Groq Llama 3.3 kullanarak senaryoyu parse et."""
        if not self._api_key:
            return super().parse_and_convert(text)

        import subprocess
        import json

        prompt = f"""Sen bir mobil test uzmanısın. Aşağıdaki doğal dil test senaryosunu Maestro YAML formatına dönüştür.

SENARYO:
{text}

{f"App ID: {self.app_id}" if self.app_id else ""}

Maestro komutları (SADECE bunları kullan):
- launchApp
- tapOn: "element_text"
- inputText: "text_to_type"
- assertVisible: "text_to_check"
- scroll
- pressBack
- swipe:
    direction: UP/DOWN/LEFT/RIGHT
    duration: 500

YAML formatında çıktı ver. Her adım için Türkçe beklenti yorumu ekle (# ile satır sonunda).
Markdown code block KULLANMA, sadece düz YAML yaz.

Örnek çıktı:
appId: com.example.app
---
- launchApp  # Uygulama başlatıldı
- tapOn: "Giriş Yap"  # Giriş butonuna tıklandı
- assertVisible: "Hoşgeldin"  # Hoşgeldin mesajı görünmeli
"""

        try:
            # Use curl for reliable API calls
            data = json.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1000
            })

            result = subprocess.run(
                [
                    "curl", "-s", "-X", "POST",
                    "https://api.groq.com/openai/v1/chat/completions",
                    "-H", f"Authorization: Bearer {self._api_key}",
                    "-H", "Content-Type: application/json",
                    "-d", data
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            response = json.loads(result.stdout)
            yaml_content = response["choices"][0]["message"]["content"]

            # Extract expectations from comments
            expectations = []
            for line in yaml_content.split("\n"):
                if "#" in line:
                    comment = line.split("#", 1)[1].strip()
                    if comment:
                        expectations.append(comment)

            # Clean YAML
            yaml_content = yaml_content.replace("```yaml", "").replace("```", "").strip()

            print("✅ Groq AI ile parse edildi!")
            return yaml_content, expectations

        except Exception as e:
            print(f"⚠️ Groq API hatası: {e}, local parser kullanılıyor")
            return super().parse_and_convert(text)

    def parse_and_convert(self, text: str) -> tuple[str, list[str]]:
        """Groq ile parse et, başarısız olursa local parser."""
        if self._api_key:
            result = self.parse_with_groq(text)
            if result[0] and ("launchApp" in result[0] or "tapOn" in result[0]):
                return result
        return super().parse_and_convert(text)


class GeminiParser(NLPParser):
    """
    Gemini AI destekli parser - doğal dili Maestro'ya dönüştürür.
    Backup olarak kullanılır.
    """

    def __init__(self, app_id: Optional[str] = None):
        super().__init__(app_id)
        load_env()
        import os
        self._api_key = os.getenv("GEMINI_API_KEY")

    def parse_with_gemini(self, text: str) -> tuple[str, list[str]]:
        """Gemini AI kullanarak senaryoyu parse et."""
        if not self._api_key:
            # API key yoksa local parser kullan
            return self.parse_and_convert(text)

        import urllib.request
        import json

        prompt = f"""Sen bir mobil test uzmanısın. Aşağıdaki doğal dil test senaryosunu Maestro YAML formatına dönüştür.

SENARYO:
{text}

{f"App ID: {self.app_id}" if self.app_id else ""}

Maestro komutları (SADECE bunları kullan):
- launchApp
- tapOn: "element_text"
- inputText: "text_to_type"
- assertVisible: "text_to_check"
- scroll
- pressBack
- swipe:
    direction: UP/DOWN/LEFT/RIGHT
    duration: 500

YAML formatında çıktı ver. Her adım için Türkçe beklenti yorumu ekle (# ile satır sonunda).
Markdown code block KULLANMA, sadece düz YAML yaz.

Örnek çıktı:
appId: com.example.app
---
- launchApp  # Uygulama başlatıldı
- tapOn: "Giriş Yap"  # Giriş butonuna tıklandı
- assertVisible: "Hoşgeldin"  # Hoşgeldin mesajı görünmeli
"""

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self._api_key}"
            
            data = json.dumps({
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 1000
                }
            }).encode('utf-8')

            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                yaml_content = result["candidates"][0]["content"]["parts"][0]["text"]

            # Extract expectations from comments
            expectations = []
            for line in yaml_content.split("\n"):
                if "#" in line:
                    comment = line.split("#", 1)[1].strip()
                    if comment:
                        expectations.append(comment)

            # Clean YAML (remove markdown code blocks if any)
            yaml_content = yaml_content.replace("```yaml", "").replace("```", "").strip()

            return yaml_content, expectations

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                print("⚠️ Gemini rate limit aşıldı, local parser kullanılıyor")
            else:
                print(f"⚠️ Gemini API hatası: {e}, local parser kullanılıyor")
            # Fallback to local regex parser
            return super().parse_and_convert(text)

    def parse_and_convert(self, text: str) -> tuple[str, list[str]]:
        """
        Önce Gemini ile dene, başarısız olursa local parser kullan.
        """
        if self._api_key:
            # Gemini ile dene
            result = self.parse_with_gemini(text)
            if result[0] and "launchApp" in result[0].lower() or "tapOn" in result[0].lower():
                return result
        
        # Fallback to local regex parser
        return super().parse_and_convert(text)


class AIEnhancedParser(NLPParser):
    """
    AI destekli parser - karmaşık senaryolar için.
    Lokal parser başarısız olursa AI'a danışır.
    """

    def __init__(self, app_id: Optional[str] = None, ai_provider: str = "anthropic"):
        super().__init__(app_id)
        self.ai_provider = ai_provider
        self._api_key = self._get_api_key()

    def _get_api_key(self) -> Optional[str]:
        import os
        if self.ai_provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY")
        return os.getenv("OPENAI_API_KEY")

    async def parse_with_ai(self, text: str) -> tuple[str, list[str]]:
        """AI kullanarak senaryoyu parse et."""
        if not self._api_key:
            # Fallback to local parser
            return self.parse_and_convert(text)

        import httpx

        prompt = f"""Sen bir mobil test uzmanısın. Aşağıdaki doğal dil test senaryosunu Maestro YAML formatına dönüştür.

SENARYO:
{text}

{f"App ID: {self.app_id}" if self.app_id else ""}

Maestro komutları:
- launchApp
- tapOn: "element"
- inputText: "text"
- assertVisible: "text"
- scroll
- pressBack
- wait: seconds: N

Sadece YAML çıktısı ver, açıklama yapma. Her adım için beklenti yorumu ekle (# ile).
"""

        async with httpx.AsyncClient() as client:
            try:
                if self.ai_provider == "anthropic":
                    response = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-sonnet-4-20250514",
                            "max_tokens": 1000,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    yaml_content = response.json()["content"][0]["text"]
                else:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": "gpt-4o",
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 1000,
                        },
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    yaml_content = response.json()["choices"][0]["message"]["content"]

                # Extract expectations from comments
                expectations = []
                for line in yaml_content.split("\n"):
                    if "#" in line:
                        comment = line.split("#", 1)[1].strip()
                        if comment:
                            expectations.append(comment)

                # Clean YAML (remove markdown code blocks if any)
                yaml_content = yaml_content.replace("```yaml", "").replace("```", "").strip()

                return yaml_content, expectations

            except Exception as e:
                # Fallback to local parser
                return self.parse_and_convert(text)

