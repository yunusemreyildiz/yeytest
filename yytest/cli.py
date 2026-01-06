"""yeytest CLI - AI-Powered Visual Test Validation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import print as rprint

from .core.models import ValidationLevel, StepStatus
from .maestro.runner import MaestroRunner, run_test_file
from .device.adb import ADBDevice, ADBError
from .nlp.parser import NLPParser, AIEnhancedParser
from .reports.html import HTMLReporter
from .web.app import run_server

app = typer.Typer(
    name="yeytest",
    help="🐬 AI-Powered Visual Test Validation for Mobile Apps",
    add_completion=False,
)
console = Console()


def version_callback(value: bool):
    if value:
        from . import __version__
        console.print(f"[bold cyan]yeytest[/bold cyan] version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """yeytest - Maestro testlerini görsel AI doğrulaması ile çalıştırır."""
    pass


@app.command()
def run(
    test_file: Path = typer.Argument(..., help="Maestro YAML test dosyası"),
    validation: str = typer.Option(
        "hybrid",
        "--validation", "-V",
        help="Doğrulama seviyesi: none, local, ai, hybrid",
    ),
    device: Optional[str] = typer.Option(
        None,
        "--device", "-d",
        help="Hedef cihaz ID'si",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Çıktı dizini",
    ),
    provider: str = typer.Option(
        "anthropic",
        "--provider", "-p",
        help="AI provider: anthropic veya openai",
    ),
):
    """
    🚀 Maestro testini görsel doğrulama ile çalıştır.
    
    Örnek:
        yeytest run login_test.yaml --validation hybrid
    """
    if not test_file.exists():
        console.print(f"[red]❌ Test dosyası bulunamadı: {test_file}[/red]")
        raise typer.Exit(1)

    # Parse validation level
    try:
        level = ValidationLevel[validation.upper()]
    except KeyError:
        console.print(f"[red]❌ Geçersiz doğrulama seviyesi: {validation}[/red]")
        console.print("Geçerli değerler: none, local, ai, hybrid")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold cyan]yeytest[/bold cyan] - Test Çalıştırılıyor\n\n"
        f"📁 Test: [yellow]{test_file}[/yellow]\n"
        f"🔍 Doğrulama: [green]{level.value}[/green]\n"
        f"🤖 Provider: [blue]{provider}[/blue]",
        title="🐬 yeytest",
        border_style="cyan",
    ))

    async def run_with_progress():
        runner = MaestroRunner(
            validation_level=level,
            device_id=device,
            ai_provider=provider,
            output_dir=output,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Test çalışıyor...", total=None)
            
            def on_step(step_result):
                status_icon = "✅" if step_result.truly_passed else "❌"
                progress.update(
                    task,
                    description=f"{status_icon} Adım {step_result.index + 1}: {step_result.action}",
                )

            result = await run_test_file(test_file, level)
        
        return result

    result = asyncio.run(run_with_progress())

    # Show results
    console.print("\n")
    
    table = Table(title="📊 Test Sonuçları", border_style="cyan")
    table.add_column("Adım", style="dim")
    table.add_column("Aksiyon", style="cyan")
    table.add_column("Hedef", style="yellow")
    table.add_column("Maestro", justify="center")
    table.add_column("Görsel", justify="center")
    table.add_column("Durum", justify="center")

    for step in result.step_results:
        maestro_icon = "✅" if step.maestro_passed else "❌"
        
        if step.validation_result:
            visual_icon = "✅" if step.validation_result.passed else "❌"
        else:
            visual_icon = "⏭️"

        status_map = {
            StepStatus.PASSED: "[green]PASS[/green]",
            StepStatus.FAILED: "[red]FAIL[/red]",
            StepStatus.VISUAL_MISMATCH: "[yellow]GÖRSEL HATA[/yellow]",
        }
        status = status_map.get(step.status, step.status.value)

        table.add_row(
            str(step.index + 1),
            step.action,
            step.target[:30] + "..." if len(step.target) > 30 else step.target,
            maestro_icon,
            visual_icon,
            status,
        )

    console.print(table)

    # Summary
    summary = result.summary
    if result.passed:
        console.print(Panel.fit(
            f"[bold green]✅ TEST BAŞARILI[/bold green]\n\n"
            f"Toplam adım: {summary['total_steps']}\n"
            f"Süre: {summary['duration_seconds']:.2f}s",
            border_style="green",
        ))
    else:
        console.print(Panel.fit(
            f"[bold red]❌ TEST BAŞARISIZ[/bold red]\n\n"
            f"Başarılı: {summary['passed']}/{summary['total_steps']}\n"
            f"Görsel uyumsuzluk: {summary['visual_mismatches']}\n"
            f"Süre: {summary['duration_seconds']:.2f}s",
            border_style="red",
        ))
        raise typer.Exit(1)


@app.command()
def devices():
    """📱 Bağlı cihazları listele."""
    try:
        adb = ADBDevice()
        device_list = adb.get_devices()
        
        if not device_list:
            console.print("[yellow]⚠️ Bağlı cihaz bulunamadı[/yellow]")
            console.print("\nİpuçları:")
            console.print("  • Emülatör çalışıyor mu?")
            console.print("  • USB debugging açık mı?")
            console.print("  • adb devices komutunu deneyin")
            return

        table = Table(title="📱 Bağlı Cihazlar", border_style="cyan")
        table.add_column("Device ID", style="cyan")
        table.add_column("Durum", style="green")

        for device_id in device_list:
            table.add_row(device_id, "✅ Hazır")

        console.print(table)

    except ADBError as e:
        console.print(f"[red]❌ ADB Hatası: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def check():
    """🔧 Sistem gereksinimlerini kontrol et."""
    console.print(Panel.fit(
        "[bold cyan]Sistem Kontrolü[/bold cyan]",
        border_style="cyan",
    ))

    checks = []

    # ADB check
    try:
        adb = ADBDevice()
        checks.append(("ADB", True, "Yüklü"))
    except ADBError as e:
        checks.append(("ADB", False, str(e)))

    # Maestro check
    import subprocess
    try:
        subprocess.run(["maestro", "--version"], capture_output=True, check=True)
        checks.append(("Maestro", True, "Yüklü"))
    except (FileNotFoundError, subprocess.CalledProcessError):
        checks.append(("Maestro", False, "Yüklü değil. curl -Ls 'https://get.maestro.mobile.dev' | bash"))

    # Tesseract check
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        checks.append(("Tesseract OCR", True, "Yüklü (ücretsiz text tanıma)"))
    except Exception:
        checks.append(("Tesseract OCR", False, "Opsiyonel - brew install tesseract"))

    # API Keys
    import os
    if os.getenv("ANTHROPIC_API_KEY"):
        checks.append(("Anthropic API", True, "Ayarlı"))
    else:
        checks.append(("Anthropic API", False, "ANTHROPIC_API_KEY env değişkeni gerekli (opsiyonel)"))

    if os.getenv("OPENAI_API_KEY"):
        checks.append(("OpenAI API", True, "Ayarlı"))
    else:
        checks.append(("OpenAI API", False, "OPENAI_API_KEY env değişkeni gerekli (opsiyonel)"))

    # Print results
    table = Table(border_style="cyan")
    table.add_column("Bileşen", style="cyan")
    table.add_column("Durum", justify="center")
    table.add_column("Not", style="dim")

    for name, status, note in checks:
        icon = "✅" if status else "❌"
        table.add_row(name, icon, note)

    console.print(table)


@app.command()
def init():
    """📝 Örnek test dosyası oluştur."""
    example_yaml = """# yeytest - Örnek Login Testi
appId: com.example.app
---
- launchApp
- tapOn: "Email"
- inputText: "test@example.com"
- tapOn: "Password"  
- inputText: "password123"
- tapOn: "Login"
- assertVisible: "Welcome"
"""

    example_expectations = """# Test beklentileri (her adım için)
expectations:
  - "Uygulama açıldı"
  - "Email alanı seçildi"
  - "Email yazıldı"
  - "Şifre alanı seçildi"
  - "Şifre yazıldı"
  - "Login butonuna tıklandı"
  - "Hoşgeldin ekranı görünüyor"
"""

    # Write example files
    Path("example_test.yaml").write_text(example_yaml)
    Path("example_expectations.yaml").write_text(example_expectations)

    console.print("[green]✅ Örnek dosyalar oluşturuldu:[/green]")
    console.print("  • example_test.yaml")
    console.print("  • example_expectations.yaml")
    console.print("\nÇalıştırmak için:")
    console.print("  [cyan]yeytest run example_test.yaml[/cyan]")


@app.command()
def parse(
    scenario: Optional[str] = typer.Argument(None, help="Doğal dil senaryo metni"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Senaryo dosyası"),
    app_id: Optional[str] = typer.Option(None, "--app-id", "-a", help="Uygulama ID"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Çıktı YAML dosyası"),
    use_ai: bool = typer.Option(False, "--ai", help="AI destekli parsing"),
):
    """
    🔄 Doğal dil senaryosunu Maestro YAML'a dönüştür.
    
    Örnek:
        yeytest parse "Login butonuna tıkla, email yaz"
        yeytest parse -f senaryo.txt -o test.yaml
    """
    # Get input text
    if file:
        if not file.exists():
            console.print(f"[red]❌ Dosya bulunamadı: {file}[/red]")
            raise typer.Exit(1)
        text = file.read_text()
    elif scenario:
        text = scenario
    else:
        console.print("[yellow]Senaryo girin (Ctrl+D ile bitirin):[/yellow]")
        import sys
        text = sys.stdin.read()

    if not text.strip():
        console.print("[red]❌ Boş senaryo[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold cyan]Senaryo Parse Ediliyor...[/bold cyan]\n\n{text[:200]}{'...' if len(text) > 200 else ''}",
        border_style="cyan",
    ))

    # Parse
    if use_ai:
        parser = AIEnhancedParser(app_id=app_id)
        yaml_content, expectations = asyncio.run(parser.parse_with_ai(text))
    else:
        parser = NLPParser(app_id=app_id)
        yaml_content, expectations = parser.parse_and_convert(text)

    # Output
    console.print("\n[bold green]📄 Maestro YAML:[/bold green]\n")
    console.print(Panel(yaml_content, border_style="green"))

    if expectations:
        console.print("\n[bold blue]🎯 Beklentiler:[/bold blue]")
        for i, exp in enumerate(expectations, 1):
            console.print(f"  {i}. {exp}")

    # Save if output specified
    if output:
        output.write_text(yaml_content)
        console.print(f"\n[green]✅ Kaydedildi: {output}[/green]")


@app.command()
def report(
    result_dir: Path = typer.Argument(..., help="Test sonuç dizini"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Rapor çıktı dosyası"),
):
    """
    📊 Test sonuçlarından HTML rapor oluştur.
    
    Örnek:
        yeytest report ./test_results/
    """
    if not result_dir.exists():
        console.print(f"[red]❌ Dizin bulunamadı: {result_dir}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]📊 Rapor oluşturuluyor: {result_dir}[/cyan]")
    
    # TODO: Load test result from directory and generate report
    reporter = HTMLReporter(output_dir=result_dir)
    console.print("[yellow]⚠️ Bu özellik henüz tam entegre değil[/yellow]")
    console.print("Şimdilik 'yeytest run' komutu ile test çalıştırın, otomatik rapor oluşturulacak.")


@app.command()
def analyze(
    video: Path = typer.Argument(..., help="Analiz edilecek video dosyası"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Çıktı dizini"),
):
    """
    🎬 Test videosunu analiz et.
    
    Örnek:
        yeytest analyze recording.mp4
    """
    if not video.exists():
        console.print(f"[red]❌ Video bulunamadı: {video}[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold cyan]Video Analizi[/bold cyan]\n\n📹 {video}",
        border_style="cyan",
    ))

    from .video.analyzer import VideoAnalyzer

    async def run_analysis():
        analyzer = VideoAnalyzer()
        return await analyzer.analyze_video(video)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Video analiz ediliyor...", total=None)
        result = asyncio.run(run_analysis())

    # Show results
    if result["success"]:
        console.print(f"\n[green]✅ Analiz tamamlandı[/green]")
    else:
        console.print(f"\n[red]❌ Anomali tespit edildi[/red]")

    table = Table(title="📊 Analiz Sonuçları", border_style="cyan")
    table.add_column("Metrik", style="cyan")
    table.add_column("Değer", style="yellow")

    table.add_row("Toplam Frame", str(result["total_frames"]))
    table.add_row("Anomali Sayısı", str(result["anomaly_count"]))
    table.add_row("Kritik Anomali", str(result["critical_anomalies"]))

    console.print(table)

    if result["anomalies"]:
        console.print("\n[bold red]⚠️ Tespit Edilen Anomaliler:[/bold red]")
        for anomaly in result["anomalies"][:5]:  # İlk 5'i göster
            severity_icon = "🔴" if anomaly["severity"] == "high" else "🟡"
            console.print(f"  {severity_icon} Frame {anomaly['frame_index']}: {anomaly['description']}")


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host adresi"),
    port: int = typer.Option(8080, "--port", "-p", help="Port numarası"),
):
    """
    🌐 Web arayüzünü başlat.
    
    Örnek:
        yeytest web
        yeytest web --port 3000
    """
    console.print(Panel.fit(
        f"[bold cyan]yeytest Web UI[/bold cyan]\n\n"
        f"🌐 http://{host}:{port}\n\n"
        f"[dim]Durdurmak için Ctrl+C[/dim]",
        border_style="cyan",
    ))
    run_server(host=host, port=port)


if __name__ == "__main__":
    app()

