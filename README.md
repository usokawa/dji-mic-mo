# dji-mic-mo

*Master your DJI Mic Mini/Mini 2 via Web or CLI.* ✨

[![GitHub license](https://img.shields.io/github/license/usokawa/dji-mic-mo?style=flat)](https://github.com/usokawa/dji-mic-mo/blob/main/LICENSE.md)
[![Language: JavaScript / Python](https://img.shields.io/badge/Language-JavaScript%20%7C%20Python-blue.svg?style=flat)](#-python-cli)
[![GitHub stars](https://img.shields.io/github/stars/usokawa/dji-mic-mo?style=flat)](https://github.com/usokawa/dji-mic-mo/stargazers)
[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-usokawa-ea4aaa?style=flat&logo=github-sponsors)](https://github.com/sponsors/usokawa)
[![Platform: Web | Linux | ChromeOS | macOS | Android | Windows](https://img.shields.io/badge/Platform-Web%20%7C%20Linux%20%7C%20ChromeOS%20%7C%20macOS%20%7C%20Android%20%7C%20Windows-lightgrey.svg?style=flat)](#-compatibility)

## 🚀 Quick Start: Web App

No installation required. Manage your device instantly via WebUSB!

👉 **[Launch dji-mic-mo Web App](https://usokawa.github.io/dji-mic-mo/dji-mic-mo.html)**

* **🔌 USB Setup:** Using Linux or Windows? Make sure to check the [USB Setup](#-usb-setup-linux--windows) section first!
* **🔒 Security Note (WebUSB):** Everything runs 100% locally. WebUSB is browser-sandboxed and requires your explicit permission to connect.
* **🏠 Local Hosting:** Prefer running it yourself?
  ```bash
  python3 -m http.server 8000
  ```
  Then open `http://localhost:8000/dji-mic-mo.html` in your browser.

## ⚡ Ultimate Features

Unlock the absolute full potential of your DJI Mic Mini/Mini 2 with real-time controls.

### 🎧 RX
* **Audio Channel:** Choose Mono, Stereo, or Safety Track.
* **Gain:** Adjust Gain (-12dB to +12dB, 6dB steps) and Monitoring Gain (1dB steps).
* **Config:** Toggle Clipping Control, Auto Off, Receiver On/Off With Camera, and Plug-Free External Speaker.

### 🎤 TX
* **Audio Processing:** Apply Voice Tone (Regular, Rich, Bright) and activate Low Cut.
* **Noise Cancellation:** Choose Off, Basic, or Strong, or control via button.
* **Config:** Toggle Auto Off and Mic LED Off.

### 📊 Live Telemetry
* **Monitoring:** Track battery levels(1:Full, 7:Empty), charging status, and device info in real-time.

## 💻 Compatibility

* **Devices:**
  * RX: DJI Mic Mini, DJI Mic Series Mobile Receiver
  * TX: DJI Mic Mini, DJI Mic Mini 2
* **Firmware:** V02
* **Browsers:** Chrome, Edge, Opera (or Chromium-based)
  *(Note: iOS / Safari / Firefox are not supported due to lack of WebUSB support.)*
* **OS:** Linux, ChromeOS, macOS, Android, Windows (*See USB Setup below*)

## 🔌 USB Setup (Linux & Windows)

Some operating systems require additional setup to grant USB access.

### 🐧 Linux
Requires `udev` rules for user-space USB access. Apply the included rules:
```bash
sudo cp 99-dji-mic.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 🪟 Windows (⚠️ Not Recommended)
Windows requires a generic driver (e.g., WinUSB) for direct device communication.
* 🛑 **CRITICAL WARNING:** Using tools like [Zadig](https://zadig.akeo.ie/) to replace drivers **will break the device's standard audio functionality**.
* 💡 **Alternative (WSL2):** Securely pass the USB device to Linux via [usbipd-win](https://github.com/dorssel/usbipd-win) to preserve your host Windows drivers.

## 🐍 Python CLI

For terminal users: Feed JSON config to `stdin`, get live state from `stdout`.

### Requirements
* **Python 3.8+**
* **pyusb** (and a `libusb` backend)

### Installation
```bash
# Ubuntu / Debian
sudo apt install python3-usb

# Fedora / RHEL
sudo dnf install python3-pyusb

# macOS (Homebrew)
brew install libusb
python3 -m venv venv
source venv/bin/activate
pip install pyusb
```
*(Note: Linux package managers generally include `libusb`. On Windows, the WinUSB driver acts as the backend.)*

### Usage

* **Monitor Live State**
  Stream real-time status straight to your stdout:
  ```bash
  python3 dji-mic-mo.py
  ```

* **Apply Config**
  Pipe JSON config. *(Allow ~3 seconds for the program to initialize before sending commands.)*
  ```bash
  (sleep 3; echo '{"rx":{"stereo":true}}') | python3 dji-mic-mo.py
  ```

## 📜 License

Licensed under the 2-Clause BSD License. See [LICENSE.md](LICENSE.md) for details.
