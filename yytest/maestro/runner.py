"""Maestro test runner with visual validation."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import yaml

from ..core.models import (
    Screenshot,
    StepResult,
    TestCase,
    TestResult,
    ValidationLevel,
    ValidationResult,
)
from ..device.adb import ADBDevice
from ..validation.local import LocalValidator
from ..validation.ai import AIValidator


class MaestroError(Exception):
    """Maestro command failed."""
    pass


class MaestroRunner:
    """
    Maestro test runner with visual validation.
    
    Her adımda:
    1. Screenshot al (before)
    2. Maestro adımını çalıştır
    3. Screenshot al (after)
    4. Görsel doğrulama yap
    """

    def __init__(
        self,
        validation_level: ValidationLevel = ValidationLevel.HYBRID,
        device_id: Optional[str] = None,
        ai_provider: str = "anthropic",
        output_dir: Optional[Path] = None,
    ):
        self.validation_level = validation_level
        self.device = ADBDevice(device_id)
        self.local_validator = LocalValidator()
        self.ai_validator = AIValidator(provider=ai_provider) if validation_level in (
            ValidationLevel.AI, ValidationLevel.HYBRID
        ) else None
        self.output_dir = output_dir or Path(tempfile.mkdtemp(prefix="yeytest_"))

    def _validate_maestro(self) -> None:
        """Check if Maestro is available."""
        try:
            result = subprocess.run(
                ["maestro", "--version"],
                capture_output=True,
                check=True,
            )
        except FileNotFoundError:
            raise MaestroError("Maestro not found. Install: curl -Ls 'https://get.maestro.mobile.dev' | bash")
        except subprocess.CalledProcessError as e:
            raise MaestroError(f"Maestro error: {e.stderr.decode()}")

    def _generate_step_yaml(self, step: dict, step_index: int) -> Path:
        """Generate a single-step Maestro YAML file."""
        yaml_content = {
            "appId": step.get("appId", ""),
            "---": None,
        }
        
        # Create flow content
        flow = [step]
        
        yaml_path = self.output_dir / f"step_{step_index:03d}.yaml"
        
        # Write YAML manually to handle Maestro format
        with open(yaml_path, "w") as f:
            if "appId" in step:
                f.write(f"appId: {step['appId']}\n")
                f.write("---\n")
            
            # Write step
            yaml.dump(flow, f, default_flow_style=False, allow_unicode=True)
        
        return yaml_path

    def _run_maestro_step(self, yaml_path: Path) -> tuple[bool, str]:
        """Run a single Maestro step and return (success, error_message)."""
        cmd = ["maestro", "test", str(yaml_path)]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return True, ""
        return False, result.stderr or result.stdout

    async def run_test(
        self,
        test_case: TestCase,
        on_step_complete: Optional[Callable[[StepResult], None]] = None,
    ) -> TestResult:
        """
        Test case'i çalıştır ve her adımı doğrula.
        
        Args:
            test_case: Çalıştırılacak test
            on_step_complete: Her adım sonrası çağrılacak callback
        """
        self._validate_maestro()
        
        # Create output directory for this test
        test_output = self.output_dir / test_case.name.replace(" ", "_")
        test_output.mkdir(parents=True, exist_ok=True)
        screenshots_dir = test_output / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        result = TestResult(
            test_case=test_case,
            started_at=datetime.now(),
        )

        previous_screenshot: Optional[Screenshot] = None

        for i, step in enumerate(test_case.steps):
            step_start = time.time()
            
            # 1. Screenshot before
            screenshot_before = None
            if previous_screenshot:
                screenshot_before = previous_screenshot
            else:
                try:
                    screenshot_before = self.device.screenshot(
                        screenshots_dir, i, f"before_step_{i}"
                    )
                except Exception:
                    pass  # Device might not be ready yet

            # 2. Run Maestro step
            yaml_path = self._generate_step_yaml(step, i)
            maestro_passed, error_msg = self._run_maestro_step(yaml_path)

            # 3. Screenshot after
            screenshot_after = self.device.screenshot(
                screenshots_dir, i, f"after_step_{i}"
            )
            previous_screenshot = screenshot_after

            # 4. Validate
            validation_result = await self._validate_step(
                before=screenshot_before.path if screenshot_before else None,
                after=screenshot_after.path,
                expectation=test_case.expectations[i] if i < len(test_case.expectations) else None,
                step=step,
            )

            # Create step result
            step_result = StepResult(
                index=i,
                action=self._get_step_action(step),
                target=self._get_step_target(step),
                maestro_passed=maestro_passed,
                validation_result=validation_result,
                screenshot_before=screenshot_before,
                screenshot_after=screenshot_after,
                duration_ms=int((time.time() - step_start) * 1000),
                error_message=error_msg,
            )

            result.step_results.append(step_result)

            if on_step_complete:
                on_step_complete(step_result)

            # If step failed, optionally stop
            if not step_result.truly_passed:
                # Continue for now, but could add fail-fast option
                pass

        result.finished_at = datetime.now()
        return result

    async def _validate_step(
        self,
        before: Optional[Path],
        after: Path,
        expectation: Optional[str],
        step: dict,
    ) -> Optional[ValidationResult]:
        """Adım için doğrulama yap."""
        if self.validation_level == ValidationLevel.NONE:
            return None

        # Local validation first (free)
        if self.validation_level in (ValidationLevel.LOCAL, ValidationLevel.HYBRID):
            local_result = self.local_validator.validate_step(
                before=before,
                after=after,
                expected_text=expectation,
            )

            # If local passed with high confidence, skip AI
            if self.validation_level == ValidationLevel.HYBRID:
                if local_result.passed and local_result.confidence >= 0.8:
                    return local_result
                
                # If local is uncertain or failed, use AI
                if self.ai_validator and expectation:
                    ai_result = await self.ai_validator.validate(
                        screenshot=after,
                        expectation=expectation,
                        context=f"Adım: {self._get_step_action(step)} {self._get_step_target(step)}",
                    )
                    return ai_result

            return local_result

        # AI only
        if self.validation_level == ValidationLevel.AI and self.ai_validator:
            return await self.ai_validator.validate(
                screenshot=after,
                expectation=expectation or "Adım başarıyla tamamlandı",
            )

        return None

    def _get_step_action(self, step: dict) -> str:
        """Extract action from step dict."""
        actions = ["tapOn", "tap", "assertVisible", "inputText", "scroll", "swipe", "launchApp"]
        for action in actions:
            if action in step:
                return action
        return list(step.keys())[0] if step else "unknown"

    def _get_step_target(self, step: dict) -> str:
        """Extract target from step dict."""
        action = self._get_step_action(step)
        target = step.get(action, "")
        if isinstance(target, dict):
            return target.get("id", target.get("text", str(target)))
        return str(target)


async def run_test_file(
    yaml_path: Path,
    validation_level: ValidationLevel = ValidationLevel.HYBRID,
) -> TestResult:
    """Run a Maestro YAML file with validation."""
    with open(yaml_path) as f:
        content = yaml.safe_load(f)
    
    # Parse Maestro YAML into TestCase
    # This is simplified - real implementation would be more robust
    test_case = TestCase(
        name=yaml_path.stem,
        description=f"Test from {yaml_path}",
        steps=content if isinstance(content, list) else [content],
    )
    
    runner = MaestroRunner(validation_level=validation_level)
    return await runner.run_test(test_case)

