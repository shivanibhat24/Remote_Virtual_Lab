# 📑 STM32 Lab GUI Technical Manual (v6.0 Platinum)

## 🏛️ System Architecture

STM32 Lab GUI is a modular, event-driven PyQt5 application. It relies on a central `MainWindow` that manages a stack of specialized laboratory components.

### 1. The Dynamic UI Engine
- **Sidebar Navigation**: Uses a custom `QListWidget` with `Qt.UserRole` mapping to a `QStackedWidget`.
- **Dynamic Typography**: Implements a recursive visitation engine in `MainWindow`. When a theme changes, the engine traverses all children and executes `update_theme()` to force a font refresh across all headers, cards, and labels.
- **Color/Theme Core**: Themes are defined in `themes.py` using a global `T` object (e.g., `T.PRIMARY`, `T.CARD_BG`).

### 2. Instrumentation Modules

- **DSO (Digital Storage Oscilloscope)**: 
    - 500-sample buffer with 20+ FPS update rate.
    - Integrated vertical cursors for delta-time and delta-voltage measurements.
    - User-customizable Trace Colors (Native QColorDialog).
- **Function Generator (15+ Waveforms)**:
    - High-fidelity signal generation including `Sine`, `Step`, `Staircase`, `Gaussian`, and `Sinc`.
    - Supports single Pulse triggering (Half-Cycle or Full-Cycle).
- **PID Tuner**: 
    - Real-time closed-loop control of a Boost Converter target.
    - Online analysis for settling time and overshoot metrics.

### 3. Smart Integration

- **NLP Command Center**: 
    - A local grammar engine (`NLGrammar`) translates plain English into hardware commands (#CMD:K=V;).
    - Sync Engine: Commands issued via NLP automatically synchronize the UI state across relevant tabs.
- **Waveform Database**:
    - Stores Every capture with a 16-character SHA-256 hash.
    - Searchable SQLite backend for high-speed waveform comparison.

---

## 📡 Communication Protocol (TX/RX)

The GUI communicates via standard Serial (UART) or over a Cloud MQTT bridge. All packets follow the **#KEY:VALUE;** format.

### Common Commands (TX)
- `#VREG:V=3.3;` - Set output voltage to 3.3V
- `#WAVE:T=SQ;` - Set waveform to Square
- `#WAVE:F=1000;` - Set frequency to 1000Hz
- `#FG_PULSE:H` - Trigger a single half-cycle pulse

### Telemetry Packets (RX)
- `#DATA:X=1.23;` - Single sample data (Multimeter/DSO)
- `#BOOST:V=5.02;` - Feedback from the PID Boost Converter
- `#TEMP:T=45.2;` - Core temperature telemetry
- `#ACK:M=OK;` - Hardware acknowledgement

---

## ☁️ MQTT Cloud Protocol

- **NAT Traversal**: Enables remote lab access through the Mosquito global broker.
- **Topic Path**: `stm32lab/{session_id}/[tx/rx]`
- **Session Management**: Randomly generated IDs with a visitation verification prompt in `CloudTab`.

---

## 🎨 Developing New Themes

To create a new theme, add a entry to `themes.py` following this schema:
```python
ThemeName = {
   "PRIMARY": "#HEX",
   "CARD_BG": "#HEX",
   "DARK_BG": "#HEX",
   "ACCENT_BLUE": "#HEX",
   "TEXT": "#HEX",
   "BORDER": "#HEX"
}
```

---

*This document is a living manual. For the latest updates, please consult the codebase source or the repository maintainer.*
