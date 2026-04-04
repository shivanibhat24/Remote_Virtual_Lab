# STM32 Laboratory Instrumentation Suite: Technical Manual (v6.0 Platinum)

**A Comprehensive Architectural and Operational Reference for Advanced Embedded Verification and Laboratory Instrumentation.**

---

## 1. System Architecture and Design

The STM32 Laboratory Instrumentation Suite is a modular, event-driven application developed using the PyQt5 framework. The primary objective is to provide a unified dashboard for managing multiple laboratory instruments with a distraction-free, professional-grade interface.

### The Dynamic UI Synchronization Engine
- **Sidebar Navigation Control**: Implements a custom `QListWidget` with `Qt.UserRole` mapping for efficient `QStackedWidget` navigation.
- **Recursive Typography Refresh (V6.0)**: A recursive visitation algorithm traverses the UI tree upon theme changes. It executes the `update_theme()` method on all children to ensure font synchronization across all headers, cards, and digital displays.
- **Theme Architecture**: Themes are centralized in `themes.py` using a standardized `T` object (e.g., `T.PRIMARY`, `T.CARD_BG`, `T.ACCENT_BLUE`).

---

## 2. Laboratory Modules: Functional Overviews

### Oscilloscope and Multimeter (DSO)
- **High-Frequency Sampling**: 500-sample buffer with 20+ FPS update rate.
- **Measurement Interface**: Includes dual vertical cursors for Delta Time and Delta Voltage delta readout.
- **Trace Color Selection**: Native `QColorDialog` integration for signal personalization.

### Function Generator (15+ Waveforms)
- **Advanced Signal Processing**: Generates recursive and mathematical waveforms (Sine, Step, Gaussian, Sinc, etc.).
- **Triggered Capture**: Supports one-shot triggers for Pulse waveforms (Half-Cycle or Full-Cycle).

### PID Tuner (Boost Converter)
- **Closed-Loop Verification Interface**: Real-time closed-loop control of a Boost Converter target hardware.
- **Analytical Metrics**: Integrated online analysis for settling time and overshoot percentage.

---

## 3. Communication Protocols and Interfacing

The suite utilizes a standardized packet-based communication protocol designed for Serial and MQTT interfaces.

### Command Structure (Transmission)
All commands follow the `#KEY:VALUE;` format:
- `#VREG:V=3.3;` - Output voltage set to 3.3V
- `#WAVE:F=1000;` - Frequency set to 1,000 Hertz
- `#FG_PULSE:H` - Trigger single half-cycle pulse

### Telemetry Structure (Reception)
- `#DATA:X=1.23;` - Signal sampling telemetry
- `#BOOST:V=5.02;` - Feedback from the PID Boost Converter
- `#TEMP:T=45.2;` - Thermal telemetry
- `#ACK:M=OK;` - Hardware acknowledgment signal

---

## 4. Intelligent Automation and Integration

### NLP Command Parsing
- **Local Grammar Engine**: A specialized `NLGrammar` class performs rule-based parsing of natural language text into hexadecimal hardware commands.
- **UI Synchronization**: Commands issued through the NLP terminal are intercepted to automatically update the local UI states of all relevant laboratory instruments.

### Waveform Database Persistence
- **SQLite Integration**: Captures are hashed using a 16-character SHA-256 algorithm and stored in a local SQLite database for historical search and similarity comparison.

---

## 5. MQTT Cloud and NAT Traversal

- **Broker Infrastructure**: Uses the Mosquitto global broker for remote NAT-to-NAT communication.
- **Client Protocol**: `stm32lab/{session_id}/[tx/rx]`
- **Session Security**: Dynamic session ID generation on startup with a visitation prompt for user verification.

---

*This technical manual is maintained for the STM32 Lab GUI v6.0 Platinum codebase. For technical support, please refer to the source documentation in the primary repository.*
