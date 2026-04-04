# Remote Virtual Lab — STM32 Electronics Lab GUI

Desktop control panel for an STM32-based remote electronics lab: multimeter/DSO view, function generator, PID tuning, DSP, protocol decode, natural-language commands, and optional MQTT cloud relay.

**Repository:** [github.com/shivanibhat24/Remote_Virtual_Lab](https://github.com/shivanibhat24/Remote_Virtual_Lab)

## Features

- **Instruments:** Multimeter + DSO buffer, function generator (15+ waveforms, 0–1 MHz UI range), Bode/trigger, voltage regulator tab, PID tuner.
- **Analysis:** Math channels, DSP pipeline (SciPy), protocol decoder (UART/I2C/SPI/1-Wire heuristics), waveform database, uncertainty and power tools.
- **Automation:** **Natural Language Command** tab (local rule-based parser, no API keys), Python REPL, production test mode, SCPI server tab.
- **Infrastructure:** Serial connection manager, themes, settings persistence, optional MQTT bridge.

## Requirements

- Python 3.10+ recommended (3.8+ supported).
- STM32 firmware that understands the lab’s `#COMMAND;` serial protocol.
- USB serial to the board.

## Install

```bash
git clone https://github.com/shivanibhat24/Remote_Virtual_Lab.git
cd Remote_Virtual_Lab
pip install -r requirements.txt
```

## Run

```bash
python stm32_lab_gui.py
```

Use **Tools → Settings** for theme and global sample period.

## Natural language commands

The **NL Command** tab turns plain English into serial commands and **updates the matching tabs** (e.g. Function Generator frequency and waveform, Voltage Reg setpoint).

Examples:

| You type | Effect |
|----------|--------|
| `square wave at 400 kHz` | Sends `#WAVE:T=SQ;` and `#WAVE:F=400000;`, FG tab shows square + 400000 Hz |
| `400kHz sine wave` | Parses frequency first, then shape |
| `set frequency to 2500 Hz` | Frequency only |
| `set output to 3.3V` | Voltage regulator command + tab sync |
| `what is the dominant frequency?` | Reads live analytics (does not reprogram FG) |

Frequencies accept **Hz**, **kHz** / **K**, and **MHz**. If your firmware cannot run at very high rates, clamp limits in firmware or in `data_engine.CommandBuilder.wave_freq`.

## Documentation

See **[DOCUMENTATION.md](DOCUMENTATION.md)** for protocol overview, architecture, and module notes.

## License / support

Developed for teaching and embedded lab use. Adjust serial commands and limits to match your STM32 build.
