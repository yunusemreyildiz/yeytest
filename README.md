# 🐬 yeytest

**AI-Powered Visual Test Validation for Mobile Apps**

Cross-platform mobile test automation framework with intelligent visual validation, built on top of Maestro.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

---

**Documentation | [Get Started](#-quick-start) | [Features](#-features) | [Why yeytest?](#-why-yeytest)**

---

yeytest is an intelligent test automation framework that provides **visual AI validation** for Maestro tests. Unlike traditional test frameworks that only check if a command executed, yeytest ensures your tests **actually work correctly** by validating visual outcomes.

## 🚀 Problem

Traditional test frameworks have a blind spot:
- ✅ `click` command executed → Test **PASS**
- ❌ But did it click the right element? Did the expected action occur? **Unknown!**

## 💡 Solution

yeytest validates every step:
1. 📸 Takes a screenshot **before** the action
2. 🎬 Executes the Maestro step
3. 📸 Takes a screenshot **after** the action
4. 🔍 Performs visual validation (local or AI-powered)
5. ✅ Confirms the test **actually worked** as expected

## ⚡ Quick Start

### Installation

```bash
# Install yeytest
pip install yeytest

# Requirements
# - Maestro CLI: curl -Ls 'https://get.maestro.mobile.dev' | bash
# - ADB (Android SDK) for Android testing
# - Xcode Command Line Tools for iOS testing
# - Optional: Tesseract OCR (free text recognition)
```

### Basic Usage

```bash
# System check
yeytest check

# List connected devices
yeytest devices

# Run a test with visual validation
yeytest run login_test.yaml

# Natural language → Maestro YAML
yeytest parse "Login butonuna tıkla, email yaz"

# Start web UI
yeytest web
```

## 🎯 Features

### 🤖 Natural Language Processing
Convert human-readable test scenarios into Maestro YAML automatically using AI:
```bash
yeytest parse "1. Uygulamayı aç 2. Login butonuna tıkla 3. Email yaz"
```

### 🧠 AI-Powered Visual Validation
- **Local validation** (free): Pixel diff, OCR, error detection
- **AI validation** (Claude/GPT Vision): Complex scenario analysis
- **Hybrid mode**: Smart fallback - local first, AI when needed (~80% cost savings)

### 🔄 Self-Healing Tests
Automatically analyze failed tests, fix issues, and retry until success:
- AI analyzes error logs
- Suggests fixes to test steps
- Re-runs tests automatically
- Maximum retry limit protection

### 🌐 Web Dashboard
Beautiful, modern web interface for:
- Test creation and management
- Batch test execution
- Real-time test monitoring
- Visual result analysis
- Self-healing test configuration

### 📱 Multi-Platform Support
- **Android**: Full ADB integration, emulator management
- **iOS**: Simulator support via xcrun simctl
- **Cross-platform**: Run the same tests on both platforms

## 🔍 Validation Levels

| Level | Cost | Description |
|-------|------|-------------|
| `none` | Free | Only Maestro result |
| `local` | Free | Pixel diff + OCR + error detection |
| `ai` | API cost | Claude/GPT Vision analysis |
| `hybrid` | Optimized | Local first, AI when suspicious |

## 💰 Cost Optimization

**Hybrid mode** minimizes costs:
- Most cases: Free local validation is sufficient
- Only suspicious cases: AI call
- ~80% cost savings compared to full AI validation

## 🏗️ Architecture

```
yeytest/
├── core/           # Data models
├── device/         # ADB & iOS integration
│   ├── adb.py      # Android device management
│   └── ios.py      # iOS simulator management
├── maestro/        # Maestro runner
├── validation/     # Validation engines
│   ├── local.py    # Pixel diff, OCR, error detection
│   └── ai.py       # Claude/GPT Vision
├── nlp/            # Natural language processing
│   └── parser.py   # AI-powered NLP → Maestro YAML
├── web/            # Web dashboard
│   └── app.py      # Full-featured web UI
├── reports/        # HTML report generation
└── cli.py          # Command-line interface
```

## 🛠️ Configuration

### AI Validation (Optional)

```bash
# Groq API (free tier available)
export GROQ_API_KEY="gsk-..."

# Or use Claude/OpenAI
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

### Environment Variables

```bash
# Test storage directories
export YEYTEST_TESTS_DIR="./yeytest_tests"
export YEYTEST_RESULTS_DIR="./yeytest_results"
```

## 📊 Output

```
📊 Test Sonuçları
┌──────┬──────────┬────────────┬─────────┬────────┬──────────────┐
│ Adım │ Aksiyon  │ Hedef      │ Maestro │ Görsel │ Durum        │
├──────┼──────────┼────────────┼─────────┼────────┼──────────────┤
│ 1    │ launchApp│ ...        │ ✅      │ ✅     │ PASS         │
│ 2    │ tapOn    │ Login      │ ✅      │ ❌     │ GÖRSEL HATA  │
└──────┴──────────┴────────────┴─────────┴────────┴──────────────┘
```

## 🎮 All Commands

```bash
# System check
yeytest check

# Device management
yeytest devices

# Test execution
yeytest run login_test.yaml --validation hybrid

# Natural language → Maestro YAML
yeytest parse "Login butonuna tıkla, email yaz"
yeytest parse -f senaryo.txt -o test.yaml --ai

# Video analysis
yeytest analyze recording.mp4

# Generate report
yeytest report ./test_results/

# Web dashboard
yeytest web
yeytest web --port 3000
```

## 🌟 Why yeytest?

1. **Visual Validation**: Don't just check if a command ran - verify it worked correctly
2. **AI-Powered**: Intelligent test generation and self-healing capabilities
3. **Cost-Effective**: Hybrid validation mode minimizes API costs
4. **Cross-Platform**: Same tests work on Android and iOS
5. **Natural Language**: Write tests in plain language, convert to Maestro automatically
6. **Modern UI**: Beautiful web dashboard for test management
7. **Self-Healing**: Automatically fix and retry failed tests
8. **Open Source**: Free, MIT licensed, community-driven

Investing in yeytest means you're betting on intelligent, visual test validation that goes beyond simple command execution. Don't settle for tests that pass but don't actually work!

## 🚧 Roadmap

- [x] Core framework
- [x] Maestro integration
- [x] Local validation (pixel diff, OCR)
- [x] AI validation (Claude, GPT-4o, Groq)
- [x] Natural language → Maestro converter
- [x] HTML reporting
- [x] Web dashboard
- [x] iOS support
- [x] Self-healing tests
- [ ] Cloud service (SaaS)
- [ ] CI/CD integrations
- [ ] Video analysis enhancements
- [ ] More AI providers

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

**yeytest** - Ensure your tests actually work. 🐬

For more information, visit [yeytest.dev](https://yeytest.dev) (coming soon)
