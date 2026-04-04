# STM32 Remote Electronics Lab - v6.0

Welcome to the **STM32 Remote Electronics Lab**, a comprehensive, offline, pure-Python measurement and automation suite designed for the STM32 Bluepill. This application transforms a simple microcontroller and an FTDI serial interface into a sophisticated desktop laboratory ecosystem.

**Version:** 6.0  
**Language:** Python 3.10+  
**Dependencies:** `PyQt5`, `pyqtgraph`, `numpy`, `pyserial`, `websockets` (Extras: `scipy`, `scikit-learn`, `pandas`)

---

## Features

The laboratory application previously relied on a horizontal tab bar, but as of v6.0 it utilizes a modern **Sidebar Dashboard Interface**, organizing all modules logically into four primary categories.

### Tier 1 Core Instruments
1. **Multimeter & Oscilloscope:** A rolling 500-sample DSO plotting raw ADCs. Includes **Dual Delta T/Delta V Cursors**, click-to-annotate markings, eye-diagram overlay extraction, and vector graphic (SVG) export.
2. **Function Generator:** Generate Sine, Square, Triangle, and Sawtooth waves across variable frequencies.
3. **Voltage Regulator & Boost:** Closed-loop software control of an external RC-filtered DAC or boost-converter output with realtime thermistor reading and 1st-order software PID modeling.
4. **Bode Plotter:** Execute frequency sweeps to extract Bode Magnitude plots (dB) tracking filter roll-offs automatically.
5. **Triggered Capture:** Classic benchtop trigger detection (Rising/Falling Edge + Level thresholds) providing single-shot synchronized captures.
6. **DSP Pipeline:** Realtime filtering using Scipy filters (Butterworth low-pass, Chebyshev high-pass, FIR windows) overlaid upon the live waveform.
7. **Protocol Decoder:** Translates raw digital edge transitions (SPI/I2C/UART/1-Wire) back into human-readable data bytes spanning logical timing frames.
8. **CSV/SQLite Playback:** Scrub through historical data logs, re-processing historic datasets through the active analytics engines.

### Tier 2 Analysis & Automation
9. **Math / Differential Channels:** Evaluate live Python and numpy expressions (e.g. `diff(CH1)`, `cumsum(CH1)`, `-CH1`) to simulate multiple functional differential signal paths.
10. **Power Profile Analyser:** Calculate hardware dynamic power estimations (V^2/R), accumulating operational Energy (mWh), and threshold-detect sleep-vs-wake sequences automatically on a timeline.
11. **Uncertainty Quantification:** Generates standard statistical +/- 1 sigma to 3 sigma signal margins including quantization limits, and auto-generates '+/-' strings for LaTeX academic papers.
12. **Python REPL Console:** Control the instruments programmatically in application memory (`lab.set_frequency(50)`).
13. **Natural Language Commands:** An offline regex-keyword parser matching plain English (`"Set the sine wave to 400 hz"`) to hardware action endpoints.

### Tier 3 Management & Documentation
14. **Waveform Database:** Categorize historic signatures, save anomalies to a SQLite db, and project them permanently onto the DSO grid to overlay comparative traces.
15. **AI Anomaly Detector:** Offloads continuous monitoring to an `IsolationForest` or 3-sigma `scikit-learn` model detecting unexpected voltage drift or mechanical faults.
16. **Calibration Wizard:** Performs automatic polynomial curve-fitting mapped to a known reference standard, injecting accuracy-correction variables into the math backend.
17. **Experiment Journal:** A rich-text note editor capable of embedding time-series tags and capturing application state, capable of saving raw HTML/Markdown notes.
18. **Production Test Mode:** Validates continuous serial-number testing. Checks multi-variable bounds against a JSON spec, displays a mass PASS/FAIL, and writes compliance documentation to CSV/SQLite.

### Logging & Infrastructure
19. **LXI / SCPI TCP Server:** The application hosts a standard port 5025 socket server mimicking enterprise Keysight hardware, parsing commands (`MEAS:VOLT:DC?`, `*IDN?`) seamlessly bridging Python to LabVIEW/MATLAB.
20. **Headless Jupyter API:** Includes an integrated module (`stm32lab`) for launching automated tests inside IPython Notebooks entirely detached from the GUI.
21. **Hot-Reloadable Plugins:** Custom UI panels drop directly into `~/.stm32lab/plugins/` without modifying core code. They automatically append themselves to the Sidebar.
22. **Global MQTT Cloud Relay:** Share your instruments securely with students globally. Connects directly to the Open-Source `test.mosquitto.org` broker natively bypassing university NATs and router firewalls without any setup. Clients utilize a standalone `global_dashboard.html` WebSocket client.

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

See the full `DOCUMENTATION.md` for architectural concepts, data framing models, SCPI protocol bindings, and custom plugin creation structures.
