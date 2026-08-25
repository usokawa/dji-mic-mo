# dji-mic-mo

*Open-source browser and CLI control for your DJI Mic Mini series.* ✨

[![GitHub license](https://img.shields.io/github/license/usokawa/dji-mic-mo?style=flat)](https://github.com/usokawa/dji-mic-mo/blob/main/LICENSE.md)
![Language: JavaScript / Python](https://img.shields.io/badge/Language-JavaScript%20%7C%20Python-blue.svg?style=flat)
[![GitHub stars](https://img.shields.io/github/stars/usokawa/dji-mic-mo?style=flat)](https://github.com/usokawa/dji-mic-mo/stargazers)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-usokawa-ea4aaa?style=flat&logo=github-sponsors)](https://github.com/sponsors/usokawa)
[![Platform: Web | Linux | ChromeOS | Android | macOS | Windows](https://img.shields.io/badge/Platform-Web%20%7C%20Linux%20%7C%20ChromeOS%20%7C%20Android%20%7C%20macOS%20%7C%20Windows-lightgrey.svg?style=flat)](#-compatibility)

**No Smartphone App Required.** dji-mic-mo is an open-source tool that brings most of the functionality of the official DJI MIMO app directly to your browser or terminal. Skip the hassle of connecting to a mobile app just to change a setting. Keep your workflow seamless while recording or streaming on Linux, ChromeOS, Android, macOS, or Windows, and adjust audio parameters instantly without reaching for your phone.

**Zero Installation.** Just open the web page and connect, or use the Python CLI for terminal control. Access all advanced features like 32-bit Float recording, Noise Cancellation, and Gain control instantly. The web version runs locally in your browser using standard WebUSB and Web Bluetooth APIs, ensuring a fast and secure connection.

## 🚀 Quick Start: Web App

No installation required! Choose your connection method to manage your device instantly:

* **🔌 USB Mode (RX Hub):** Connect the Receiver via USB to control the entire system (RX + all TXs).

  👉 **[Launch USB Web App](https://usokawa.github.io/dji-mic-mo/dji-mic-mo.html)**

* **📶 Bluetooth Mode (TX Direct):** Connect directly to a Transmitter via Bluetooth for standalone configuration.

  👉 **[Launch Bluetooth Web App](https://usokawa.github.io/dji-mic-mo/dji-mic-mo-ble.html)**

* **⚠️ Important Setup:** Using Linux or Windows? Make sure to read the [Setup & Troubleshooting](#-setup--troubleshooting) section before connecting!
* **🔒 Security Note:** Everything runs 100% locally. WebUSB and Web Bluetooth are browser-sandboxed and require your explicit permission to connect.
* **🏠 Local Hosting:** Prefer running it yourself?
  ```bash
  python3 -m http.server 8000
  ```
  Then open `http://localhost:8000/dji-mic-mo.html` (or `-ble.html`) in your browser.

## ⚡ Ultimate Features

Unlock the absolute full potential of your DJI Mic Mini series with real-time controls.

> **Device Tags Legend:**
> * `[Mobile RX]`: DJI Mic Series Mobile Receiver
> * `[Mini / 2S RX]`: DJI Mic Mini / Mini 2S Receiver
> * `[Mini 2 / 2S]`: DJI Mic Mini 2 / Mini 2S Transmitter
> * `[Mini 2S]`: DJI Mic Mini 2S Transmitter
>
> *(Features without tags are supported across all applicable devices)*

### 🎧 RX (USB Only)
* **Audio Channel:** Choose Mono, Stereo, Quadraphonic `[Mini 2S RX]`, or Safety Track.
* **Gain:** Adjust Gain (-12dB to +12dB, 6dB steps) `[Mobile RX]` and Monitoring Gain (1dB steps) `[Mobile RX]`.
* **Config:** Toggle Clipping Control, Auto Off `[Mini / 2S RX]`, Receiver On/Off With Camera `[Mini / 2S RX]`, and Plug-Free External Speaker.

### 🎤 TX (USB or Bluetooth)
* **Audio & NC:** Activate Low Cut, and choose Noise Cancellation mode (Off, Basic, Strong, or via button). Apply Voice Tone (Regular, Rich, Bright) `[Mini 2 / 2S]`, and control Transmitter Gain (1dB steps) `[Mini 2S]`.
* **Gain Control:** Toggle Adaptive Gain Control settings: Clipping Control, and Loudness Balance `[Mini 2S]`.
* **Internal Recording `[Mini 2S]`:** Start/Stop local recording, enable 32-bit Float Recording, Auto Recording modes (Startup, With Receiver, Low Power), Loop Recording, configure File Options, **and Format (Delete all data)**.
* **System & Config:** Toggle Auto Off, Mic LED Off, and Vibration `[Mini 2S]`.

> **⚠️ Caution:** The Format feature will instantly delete all internal recordings on the TX. Please handle with care.

### 📊 Live Telemetry
* **Monitoring:** Track battery levels (1:Full, 7:Empty) and charging status `[Mini / 2S RX]`, plus real-time device info.
* **Recording Status `[Mini 2S]`:** Monitor Total and Remaining Recording Time dynamically.

## 💻 Compatibility

* **Devices:**
  * RX: DJI Mic Series Mobile Receiver, DJI Mic Mini, DJI Mic Mini 2S
  * TX: DJI Mic Mini, DJI Mic Mini 2, DJI Mic Mini 2S
* **Firmware:** V02 (Mini / Mini 2), V30 (Mini 2S)
* **Browsers:** Chromium-based browsers (Chrome, Edge, Opera, etc.)
  *(Note: iOS / Safari / Firefox are not supported due to lack of WebUSB / Web Bluetooth support.)*
* **OS:** Linux, ChromeOS, Android, macOS, Windows (*See Setup below*)

## 🔌 Setup & Troubleshooting

Some operating systems require additional setup to grant hardware access.

### 🐧 Linux
* **USB:** Requires `udev` rules for user-space USB access. Apply the included rules:
  ```bash
  sudo cp 99-dji-mic.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  ```
* **Bluetooth (Web):** In Chromium-based browsers, you may need to enable `chrome://flags/#enable-experimental-web-platform-features` (or `edge://flags/...`) for Web Bluetooth to work.

### 🪟 Windows (⚠️ USB Not Recommended)
Windows requires a generic driver (e.g., WinUSB) for direct device communication via USB.
* 🛑 **CRITICAL WARNING:** Using tools like [Zadig](https://zadig.akeo.ie/) to replace drivers **will break the device's standard audio functionality**.
* 💡 **Alternative (WSL2):** Securely pass the USB device to Linux via [usbipd-win](https://github.com/dorssel/usbipd-win) to preserve your host Windows drivers.
*(Note: Bluetooth connection works natively on Windows without driver modifications.)*

## 🐍 Python CLI

For terminal users: Feed JSON config to `stdin`, get live state from `stdout`.

### Requirements
* **Python 3.8+**
* **pyusb** (for USB) and **bleak** (for Bluetooth)

### Installation
```bash
# Ubuntu / Debian
sudo apt install python3-usb python3-bleak

# Fedora / RHEL
python3 -m venv venv
source venv/bin/activate
pip install pyusb bleak

# macOS (Homebrew)
brew install libusb
python3 -m venv venv
source venv/bin/activate
pip install pyusb bleak

# Windows
# Note: We strongly recommend using WSL2 for USB.
# Install only 'bleak' on native Windows for Bluetooth:
python -m venv venv
venv\Scripts\activate
pip install bleak
```

### Usage

*(Note: On Windows, use `python` instead of `python3` in the commands below.)*

* **Monitor Live State**

  Stream real-time status straight to your stdout:
  ```bash
  # For USB (RX Hub)
  python3 dji-mic-mo.py

  # For Bluetooth (TX Direct)
  python3 dji-mic-mo-ble.py
  ```

* **Apply Config**

  Pipe JSON config to `stdin`. *(Allow a few seconds for the program to initialize before sending commands.)*

  *Example: Set RX to Stereo (USB Only)*
  ```bash
  (sleep 3; echo '{"rx":{"stereo":true}}') | python3 dji-mic-mo.py
  ```

  *Example: Start recording on TX (Bluetooth)*
  ```bash
  (sleep 10; echo '{"tx":{"rec":true}}') | python3 dji-mic-mo-ble.py
  ```

## 📜 License

Licensed under the 2-Clause BSD License. See [LICENSE.md](LICENSE.md) for details.
