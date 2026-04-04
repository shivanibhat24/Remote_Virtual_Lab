# Remote Virtual Lab — Technical Documentation (v6.x)

Operational reference for the PyQt5 **STM32 Lab GUI** in this repository.

## Architecture

- **Entry point:** `stm32_lab_gui.py` — `MainWindow` builds tabs, wires serial I/O, and synchronizes settings.
- **Themes:** `themes.py`, `styles.py`, `widgets.py` — shared typography and cards.
- **Serial:** `serial_manager.py` — connect/disconnect, read loop feeding `DataParser`.
- **Parsing:** `data_engine.py` — `DataParser` for `#KIND:KEY=VAL,...;` frames, `CommandBuilder` for outbound commands, `AnalyticsEngine` for rolling stats.

## Serial protocol (summary)

Outbound examples:

- `#VREG:V=3.3;` — regulator setpoint  
- `#WAVE:T=SQ;` — waveform type code  
- `#WAVE:F=1000;` — frequency (Hz), clamped in `CommandBuilder.wave_freq` (default cap 1 MHz in software; must match firmware)  
- `#PID:...`, `#BOOST:...` — see firmware docs  

Inbound examples: `#DATA:X=...`, `#ACK:...`, `#ERR:...`, `#BOOST:...`, `#TEMP:...`.

## Natural language command (NL) pipeline

**Module:** `tab_nlcmd.py` — class `NLGrammar`.

1. User text is classified (measurement question vs. command).  
2. **Measurement** queries (e.g. dominant frequency, voltage stats) use `AnalyticsEngine.stats()` only — they do not change the function generator.  
3. **Wave + frequency** commands parse shape and numeric frequency (Hz / kHz / MHz) and emit `#WAVE:T=...;` then `#WAVE:F=...;`.  
4. `MainWindow._on_nlp_command_sent` sends each line to the device **and** parses it again with `DataParser` to update:
   - **Function Generator** tab — `_select_wave()` and `spin_freq`  
   - **Voltage Reg** tab — `spin_vreg` for `#VREG:...`  

**Bug fix note:** UI sync previously referenced a non-existent `tab_voltreg` attribute; it now uses `tab_vreg` and structured parsing so FG and regulator controls stay aligned with NLP.

## Function generator UI range

`tab_funcgen.py` exposes **0–1,000,000 Hz** in the spin box and slider so high-frequency NLP commands (e.g. 400 kHz) display correctly. Confirm your STM32 waveform timer supports the requested frequency.

## DSP and protocol tabs

- **DSP:** `tab_dsp.py` — SciPy-based chain on the DSO buffer; `sample_period` follows global settings.  
- **Protocol:** `tab_protocol.py` — thresholded decoders; sample rate comes from the on-tab **Hz** control (synced from global settings).

## MQTT / cloud

Optional bridge in `mqtt_bridge.py`; REPL/cloud tabs depend on installed extras (`websockets`).

## Settings persistence

`settings_manager.py` stores window geometry, theme, sample period, and selected widget values (including FG frequency and regulator voltage).

---

*This manual matches the `Remote_Virtual_Lab` codebase. Update command caps and protocol details to reflect your firmware revision.*
