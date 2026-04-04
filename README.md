# STM32 Remote Electronics Lab - v6.0 Gold (Enhanced)

Welcome to the **STM32 Remote Electronics Lab**, a comprehensive, offline, pure-Python measurement and automation suite designed for the STM32 Bluepill. This application transforms a simple microcontroller and an FTDI serial interface into a sophisticated desktop laboratory ecosystem.

**Version:** 6.0 Gold  
**Language:** Python 3.10+  
**Official Repository:** [Remote_Virtual_Lab](https://github.com/shivanibhat24/Remote_Virtual_Lab)  
**Dependencies:** `PyQt5`, `pyqtgraph`, `numpy`, `pyserial`, `websockets` (Extras: `scipy`, `scikit-learn`, `pandas`)

---

## What's New in v6.0 Gold?

### 🎨 Premium Visual Experience
- **10 Consolidated Themes**: A curated selection of high-fidelity palettes including *Everforest*, *Rose Pine*, *Synthwave '84*, *Cyberpunk*, and *GitHub Dimmed*.
- **Dynamic Formal Typography**: Features a recursive font synchronization engine. Switching themes instantly swaps your typography between **Serif** (e.g., Academic/Notebook) and **Sans-Serif** (e.g., Modern/Cyberpunk) across all sidebars and digital displays.

### 🧪 Professional-Grade Function Generator
The Function Generator has been expanded into a **15+ Waveform Laboratory Module** with a new dual-tab interface:
- **PRIMARY Tab**: Rapid access to `Square`, `Triangle`, and `Parabola`.
- **OTHER (Advanced) Tab**: A specialized tray for `Sine`, `Half-Wave`, `Full-Wave`, `Sinc`, `Step`, `Sawtooth`, `Staircase`, `Gaussian`, `DC`, and `White Noise`.
- **Single Pulse Trigger**: A dedicated **[ SINGLE PULSE ]** hardware trigger for one-shot transient testing.

### 📸 Intelligent Data Capture
- **Session-Based Screenshots**: Select your capture directory once per session. The application remembers your choice, automatically saving all subsequent PNGs, SVGs, and DSO plots to your preferred location until the app is closed.

---

## Core Features

The laboratory application utilizes a modern **Sidebar Dashboard Interface**, organizing all modules logically into four primary categories.

### Tier 1 Core Instruments
1. **Multimeter & Oscilloscope:** A rolling 500-sample DSO plotting raw ADCs. Includes **Dual Delta T/Delta V Cursors**, click-to-annotate markings, and vector graphic (SVG) export.
2. **Advanced Function Generator:** 15+ signal types with real-time mathematical preview.
3. **Voltage Regulator & Boost:** Closed-loop software control with 1st-order software PID modeling.
4. **Bode Plotter:** Automatic frequency sweeps tracking filter roll-offs (dB).
5. **Triggered Capture:** Synchronized single-shot captures with adjustable level/edge thresholds.
6. **DSP Pipeline:** Real-time SciPy filtering (Butterworth, Chebyshev, FIR) overlaid on live traces.
7. **Protocol Decoder:** Logic analysis for SPI, I2C, UART, and 1-Wire.
8. **CSV/SQLite Playback:** Scrub through historical logs and re-process datasets.

### Tier 2 Analysis & Automation
9. **Math / Differential Channels:** Live Python/NumPy expressions for complex signal paths.
10. **Power Profile Analyser:** Dynamic power estimation (V^2/R) and energy accumulation (mWh).
11. **Uncertainty Quantification:** Statistical margins (+/- sigma) and LaTeX-ready strings.
12. **Python REPL Console:** Direct programmatic control of the lab backend.
13. **Natural Language Commands:** Speak or type plain English commands to the hardware.

### Tier 3 Management & Documentation
14. **Waveform Database:** SQLite-backed signature categorization and trace overlay.
15. **AI Anomaly Detector:** `IsolationForest` monitoring for drift or mechanical faults.
16. **Calibration Wizard:** Polynomial curve-fitting for hardware accuracy correction.
17. **Experiment Journal:** Rich-text editor with time-series tags and HTML/Markdown export.
18. **Production Test Mode:** Automated pass/fail validation against JSON specifications.

### Logging & Infrastructure
19. **LXI / SCPI TCP Server:** Enterprise-standard port 5025 server for LabVIEW/MATLAB bridging.
20. **Headless Jupyter API**: Automated testing via the `stm32lab` Python module.
21. **Hot-Reloadable Plugins**: Drop-in UI panels for unlimited custom expansion.
22. **Global MQTT Cloud Relay**: Native remote access bypassing NATs for global collaboration.

---

## Setup & Installation

1. Create a Python Virtual Environment:
   ```bash
   python -m venv venv
   source venv/bin/activate    # Linux/Mac
   # OR: .\venv\Scripts\activate # Windows
   ```
2. Install the necessary dependencies:
   ```bash
   pip install PyQt5 pyqtgraph pyserial websockets numpy
   pip install scipy scikit-learn pandas  # Optional for advanced analytical modules
   ```
3. Run the GUI:
   ```bash
   python stm32_lab_gui.py
   ```

To interact programmatically via IPython/Jupyter without opening the GUI:
```python
from stm32lab import STM32Lab
lab = STM32Lab(port="COM3")
df = lab.sweep_bode(f_start=10, f_stop=100_000)
print(df.head())
```

© 2026 shivanibhat24. Licensed for educational and research use.
