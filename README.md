# 🔬 STM32 Lab GUI v6.0 Platinum

[![Version](https://img.shields.io/badge/Version-6.0_Platinum-gold.svg)](https://github.com/shivanibhat24/Remote_Virtual_Lab)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)

**The ultimate professional-grade laboratory ecosystem for STM32 and embedded verification.** 

STM32 Lab GUI v6.0 is a modular, high-performance instrumentation suite designed for electronics education, hardware verification, and remote laboratory experiments. Built with a signature **Platinum UI** and a recursive **Dynamic Typography Engine**, it provides a stunning, distraction-free environment for deep engineering work.

---

## 🌟 Key Highlights

### 🎨 Premium Design System
Experience the project in **10 handcrafted themes**, from the deep-space `Obsidian` to the vibrant `Nord` and `Solarized`. Features a recursive sync engine that refreshes real-time typography across all 100+ sidebar elements simultaneously.

### 🧠 AI & Natural Language
- **NLP Command Center**: Control your lab using plain English. *"Set frequency to 1kHz"*, *"Show me a triangle wave"*, or *"What is the RMS voltage?"*.
- **Anomaly Detection**: Integrated DSP and statistical monitoring for signal integrity analysis.

### 🛰️ Global Cloud Relay
Built-in **MQTT NAT Traversal**. Share your lab setup globally with a session-based random ID. Access your dashboard from any browser or mobile device (MQTT Dash, etc.).

---

## 🛠️ Performance Modules

| Category | Instruments & Features |
| :--- | :--- |
| **Primary** | Multimeter, DSO (Oscilloscope), Function Generator, Logic Analyzer |
| **Advanced** | PID Tuner (Boost), DSP Pipeline, Protocol Decoder |
| **Analytics** | Waveform Browser, CSV Playback, SQL Search, Frequency Domain (FFT) |
| **Automation** | Python REPL, Production Tester, AI Command Center |

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.8+**
- **STM32 Hardware** (Running the Lab Firmware)
- **High-speed Serial Connection**

### Installation
```bash
# Clone the repository
git clone https://github.com/shivanibhat24/Remote_Virtual_Lab.git
cd Remote_Virtual_Lab

# Install dependencies
pip install -r requirements.txt
```

### Usage
```bash
python stm32_lab_gui.py
```

---

## 🧬 Core Technologies
- **GUI Engine**: PyQt5 with custom `ThemeCore`
- **Plotting**: High-performance `PyQtGraph` (20+ FPS)
- **Math & DSP**: `NumPy`, `SciPy`
- **Cloud**: `Paho-MQTT`
- **Database**: `SQLite3` (Waveform history)

---

## 📜 Documentation
For a deep dive into the architecture and command protocol, please refer to:
- [**Technical Manual (DOCUMENTATION.md)**](file:///C:/Users/sg78b/Downloads/Python%20GUI%20Code/codev2/DOCUMENTATION.md)
- [**Waveform Library Reference**](file:///C:/Users/sg78b/Downloads/Python%20GUI%20Code/codev2/tab_funcgen.py)

---

> [!TIP]
> Use the **[ TRACE COLOR ]** button in the DSO tab to personalize your signal visualization for publications or presentations.

**Developed with ❤️ for the Global Electronics Engineering Community.**
