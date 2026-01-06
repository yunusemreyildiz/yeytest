"""HTML report generator."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.models import TestResult, StepStatus


class HTMLReporter:
    """
    Detaylı HTML test raporu oluşturucu.
    
    İçerik:
    - Test özeti
    - Her adımın sonucu
    - Screenshot'lar (before/after)
    - Görsel doğrulama notları
    - Zaman çizelgesi
    """

    TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>yeytest Raporu - {test_name}</title>
    <style>
        :root {{
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --text-primary: #c9d1d9;
            --text-secondary: #8b949e;
            --accent-green: #3fb950;
            --accent-red: #f85149;
            --accent-yellow: #d29922;
            --accent-blue: #58a6ff;
            --border-color: #30363d;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        header {{
            text-align: center;
            margin-bottom: 3rem;
            padding-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .logo {{
            font-size: 2.5rem;
            font-weight: bold;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-green));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .test-name {{
            font-size: 1.5rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }}
        
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 3rem;
        }}
        
        .summary-card {{
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
            border: 1px solid var(--border-color);
        }}
        
        .summary-card.passed {{
            border-color: var(--accent-green);
        }}
        
        .summary-card.failed {{
            border-color: var(--accent-red);
        }}
        
        .summary-value {{
            font-size: 2.5rem;
            font-weight: bold;
        }}
        
        .summary-label {{
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }}
        
        .steps {{
            background: var(--bg-secondary);
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }}
        
        .steps-header {{
            padding: 1rem 1.5rem;
            background: var(--bg-tertiary);
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .step {{
            padding: 1.5rem;
            border-bottom: 1px solid var(--border-color);
            transition: background 0.2s;
        }}
        
        .step:hover {{
            background: var(--bg-tertiary);
        }}
        
        .step:last-child {{
            border-bottom: none;
        }}
        
        .step-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        
        .step-number {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 0.875rem;
        }}
        
        .step-number.passed {{
            background: var(--accent-green);
            color: white;
        }}
        
        .step-number.failed {{
            background: var(--accent-red);
            color: white;
        }}
        
        .step-number.visual-mismatch {{
            background: var(--accent-yellow);
            color: black;
        }}
        
        .step-action {{
            font-weight: 600;
            color: var(--accent-blue);
        }}
        
        .step-target {{
            color: var(--text-secondary);
        }}
        
        .step-badges {{
            display: flex;
            gap: 0.5rem;
            margin-left: auto;
        }}
        
        .badge {{
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 500;
        }}
        
        .badge.maestro {{
            background: rgba(88, 166, 255, 0.2);
            color: var(--accent-blue);
        }}
        
        .badge.visual {{
            background: rgba(63, 185, 80, 0.2);
            color: var(--accent-green);
        }}
        
        .badge.visual.failed {{
            background: rgba(248, 81, 73, 0.2);
            color: var(--accent-red);
        }}
        
        .step-details {{
            margin-top: 1rem;
            padding: 1rem;
            background: var(--bg-tertiary);
            border-radius: 8px;
        }}
        
        .validation-note {{
            color: var(--text-secondary);
            font-size: 0.875rem;
        }}
        
        .screenshots {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
            margin-top: 1rem;
        }}
        
        .screenshot {{
            text-align: center;
        }}
        
        .screenshot img {{
            max-width: 100%;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }}
        
        .screenshot-label {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
        }}
        
        .timeline {{
            margin-top: 3rem;
            padding: 1.5rem;
            background: var(--bg-secondary);
            border-radius: 12px;
            border: 1px solid var(--border-color);
        }}
        
        .timeline-title {{
            font-weight: 600;
            margin-bottom: 1rem;
        }}
        
        .timeline-bar {{
            height: 8px;
            background: var(--bg-tertiary);
            border-radius: 4px;
            display: flex;
            overflow: hidden;
        }}
        
        .timeline-segment {{
            height: 100%;
        }}
        
        .timeline-segment.passed {{
            background: var(--accent-green);
        }}
        
        .timeline-segment.failed {{
            background: var(--accent-red);
        }}
        
        footer {{
            text-align: center;
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid var(--border-color);
            color: var(--text-secondary);
        }}
        
        footer a {{
            color: var(--accent-blue);
            text-decoration: none;
        }}
        
        @media (max-width: 768px) {{
            .screenshots {{
                grid-template-columns: 1fr;
            }}
            
            .step-badges {{
                flex-wrap: wrap;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">🐬 yeytest</div>
            <div class="test-name">{test_name}</div>
            <div style="color: var(--text-secondary); margin-top: 0.5rem;">
                {timestamp}
            </div>
        </header>
        
        <div class="summary">
            <div class="summary-card {overall_status}">
                <div class="summary-value">{overall_icon}</div>
                <div class="summary-label">{overall_text}</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">{total_steps}</div>
                <div class="summary-label">Toplam Adım</div>
            </div>
            <div class="summary-card">
                <div class="summary-value" style="color: var(--accent-green)">{passed_steps}</div>
                <div class="summary-label">Başarılı</div>
            </div>
            <div class="summary-card">
                <div class="summary-value" style="color: var(--accent-red)">{failed_steps}</div>
                <div class="summary-label">Başarısız</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">{duration}s</div>
                <div class="summary-label">Süre</div>
            </div>
        </div>
        
        <div class="steps">
            <div class="steps-header">📋 Test Adımları</div>
            {steps_html}
        </div>
        
        <div class="timeline">
            <div class="timeline-title">⏱️ Zaman Çizelgesi</div>
            <div class="timeline-bar">
                {timeline_html}
            </div>
        </div>
        
        <footer>
            <p>Rapor oluşturuldu: <strong>yeytest v0.1.0</strong></p>
            <p><a href="https://yeytest.dev">yeytest.dev</a></p>
        </footer>
    </div>
</body>
</html>
"""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path(".")

    def _encode_image(self, path: Path) -> str:
        """Encode image to base64 for embedding."""
        if not path.exists():
            return ""
        
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        
        return f"data:image/png;base64,{data}"

    def _generate_step_html(self, step_result) -> str:
        """Generate HTML for a single step."""
        status_class = {
            StepStatus.PASSED: "passed",
            StepStatus.FAILED: "failed",
            StepStatus.VISUAL_MISMATCH: "visual-mismatch",
        }.get(step_result.status, "pending")

        maestro_badge = "✅ Maestro" if step_result.maestro_passed else "❌ Maestro"
        
        visual_badge = ""
        if step_result.validation_result:
            if step_result.validation_result.passed:
                visual_badge = '<span class="badge visual">✅ Görsel</span>'
            else:
                visual_badge = '<span class="badge visual failed">❌ Görsel</span>'

        validation_note = ""
        if step_result.validation_result:
            validation_note = f"""
            <div class="step-details">
                <div class="validation-note">
                    <strong>🔍 Doğrulama:</strong> {step_result.validation_result.reason}<br>
                    <strong>Güven:</strong> {step_result.validation_result.confidence:.0%}<br>
                    <strong>Metod:</strong> {step_result.validation_result.method}
                </div>
            </div>
            """

        screenshots_html = ""
        if step_result.screenshot_before or step_result.screenshot_after:
            before_img = ""
            after_img = ""
            
            if step_result.screenshot_before and step_result.screenshot_before.path.exists():
                before_img = f'''
                <div class="screenshot">
                    <img src="{self._encode_image(step_result.screenshot_before.path)}" alt="Before">
                    <div class="screenshot-label">Önce</div>
                </div>
                '''
            
            if step_result.screenshot_after and step_result.screenshot_after.path.exists():
                after_img = f'''
                <div class="screenshot">
                    <img src="{self._encode_image(step_result.screenshot_after.path)}" alt="After">
                    <div class="screenshot-label">Sonra</div>
                </div>
                '''
            
            if before_img or after_img:
                screenshots_html = f'''
                <div class="screenshots">
                    {before_img}
                    {after_img}
                </div>
                '''

        return f"""
        <div class="step">
            <div class="step-header">
                <div class="step-number {status_class}">{step_result.index + 1}</div>
                <span class="step-action">{step_result.action}</span>
                <span class="step-target">{step_result.target}</span>
                <div class="step-badges">
                    <span class="badge maestro">{maestro_badge}</span>
                    {visual_badge}
                </div>
            </div>
            {validation_note}
            {screenshots_html}
        </div>
        """

    def generate(self, result: TestResult, output_path: Optional[Path] = None) -> Path:
        """Generate HTML report."""
        if output_path is None:
            output_path = self.output_dir / f"report_{result.test_case.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

        summary = result.summary
        
        # Generate steps HTML
        steps_html = "\n".join(
            self._generate_step_html(step) for step in result.step_results
        )

        # Generate timeline HTML
        total_duration = sum(s.duration_ms for s in result.step_results) or 1
        timeline_html = ""
        for step in result.step_results:
            width = (step.duration_ms / total_duration) * 100
            status_class = "passed" if step.truly_passed else "failed"
            timeline_html += f'<div class="timeline-segment {status_class}" style="width: {width}%"></div>'

        # Fill template
        html = self.TEMPLATE.format(
            test_name=result.test_case.name,
            timestamp=result.started_at.strftime("%d %B %Y, %H:%M:%S"),
            overall_status="passed" if result.passed else "failed",
            overall_icon="✅" if result.passed else "❌",
            overall_text="TEST BAŞARILI" if result.passed else "TEST BAŞARISIZ",
            total_steps=summary["total_steps"],
            passed_steps=summary["passed"],
            failed_steps=summary["failed"],
            duration=f"{summary['duration_seconds']:.1f}",
            steps_html=steps_html,
            timeline_html=timeline_html,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        
        return output_path

