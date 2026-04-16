# dji-mic-mo - A handy tool for DJI Mic Mini

![License](https://img.shields.io/github/license/usokawa/dji-mic-mo)
![Stars](https://img.shields.io/github/stars/usokawa/dji-mic-mo?style=social)

An unofficial USB settings and status monitoring tool for the DJI Mic Mini and DJI Mic Series Mobile Receiver, available as a Web Version and a Python Version.

## 🚀 Quick Start (Web Version)

No installation required! Just open the page in a supported browser, connect your device, and click "Connect Device". Settings and status update in real-time.

👉 **[Launch Web Version](https://usokawa.github.io/dji-mic-mo/dji-mic-mo.html)**

*Privacy Note: The Web Version runs 100% locally in your browser. No data or audio is sent to any external servers.*

*Note: The Web Version requires a secure context. If you download the HTML file, you must serve it via `localhost` or HTTPS, not `file:///`*

**How to serve locally via localhost:**
If you downloaded the repository and want to run the Web Version offline, you can easily start a local server using Python. Open your terminal in the downloaded folder and run:

```bash
python -m http.server
```
Then, open [http://localhost:8000/dji-mic-mo.html](http://localhost:8000/dji-mic-mo.html) in your browser.

### Supported Environments for Web Version
* **Browsers:** Chromium-based browsers (Chrome, Edge, Opera, etc.).
* **OS:**
  * **Linux:** Requires udev rules (see below).
  * **ChromeOS:** Works out of the box! No setup required.
  * **macOS:** Works out of the box! No setup required.
  * **Android:** Supported, but please use the official DJI app.
  * **iOS / Safari:** Not supported as Apple restricts the necessary Web APIs. Please use the official DJI app.
  * **Windows (Not Recommended):** Requires driver replacement via Zadig, which breaks normal audio input (see below).

## 🐍 Python Version

For advanced users who prefer the terminal, a Python Version is also available.

### Requirements
* Python: 3.10+
* Dependencies: `pyusb` and a native `libusb` backend.

**Linux:**
```bash
# Debian/Ubuntu
sudo apt install python3-usb

# Fedora/RedHat
sudo dnf install python3-pyusb
```

**macOS:**
```bash
brew install libusb
pip install pyusb
```

**Windows:**
```bash
pip install pyusb libusb
```

### Usage
Run with desired arguments. Example:
```bash
python dji-mic-mo.py --audio-channel stereo
```

### Target a Specific Device
If multiple DJI Mic receivers are connected, specify one using the `--device` flag with its `<bus>:<address>` ID.
```bash
python dji-mic-mo.py --device 1:2
```

Check `python dji-mic-mo.py --help` for all options.

## ⚙️ OS-Specific USB Setup (Linux & Windows)

These steps are required for **both** the Web Version and Python Version on specific operating systems.

### Linux
To access the device without `sudo`, copy `99-dji-mic.rules` to your udev rules and reload:
```bash
sudo cp 99-dji-mic.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Windows (Not Recommended)
Windows natively binds the DJI Mic as an audio device, blocking direct USB access. You must replace the USB driver with WinUSB via [Zadig](https://zadig.akeo.ie/).

> **⚠️ WARNING:**
> Doing so will prevent the microphone from being recognized as a standard audio input device until you roll back the driver.

## FAQ

**Q: Are you affiliated with DJI? Did you steal their secrets?**

A: No.

**Q: Is this tool for eavesdropping?**

A: No.

**Q: Is there any compensation for damages?**

A: No. Read [LICENSE.md](LICENSE.md).

**Q: What is the confirmed environment?**

A: Linux (Python 3.12, Google Chrome) and ChromeOS (Google Chrome), with the DJI Mic Mini Transmitter, Receiver, and DJI Mic Series Mobile Receiver.

**Q: Can I use it on macOS?**

A: Likely yes, but I haven't tested it. [Sponsorships wanted!](https://github.com/sponsors/usokawa)

**Q: Can I use it on Windows?**

A: Yes, but see the OS-Specific USB Setup section for why it's not recommended.

**Q: Does it work with DJI Mic 2/3?**

A: Likely no, but untested. [Sponsorships wanted!](https://github.com/sponsors/usokawa)
