# dji-mic-mo - A handy tool for DJI Mic Mini

A USB configuration and monitoring tool for the DJI Mic Mini and DJI Mic Series Mobile Receiver. Available as a Python script or a WebUSB page.

## OS-Specific USB Setup (Permissions & Drivers)
These settings are required for **both** Python and WebUSB versions to enable USB access.

* Linux:
  To access the device without `sudo`, copy [99-dji-mic.rules](99-dji-mic.rules) to your udev rules and reload:
  ```bash
  sudo cp 99-dji-mic.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  ```

* macOS:
  No special driver or permission setup is required.

* Windows (**Not Recommended**):
  Requires replacing the USB driver via [Zadig](https://zadig.akeo.ie/). Not recommended as it may disrupt normal operations.

## 1. Python Version ([dji-mic-mo.py](https://github.com/usokawa/dji-mic-mo/blob/main/dji-mic-mo.py))

### Requirements
* Python: 3.10+
* Dependencies: `pyusb` and a native `libusb` backend.

  **For Linux**
  Install the package via your package manager. This automatically installs `libusb`.
  * Debian/Ubuntu:
    ```bash
    sudo apt install python3-usb
    ```
  * Fedora/RedHat:
    ```bash
    sudo dnf install python3-pyusb
    ```

  **For macOS**
  Install `libusb` via Homebrew and `pyusb` via pip:
  ```bash
  brew install libusb
  pip install pyusb
  ```

  **For Windows**
  Install `pyusb` and the `libusb` wrapper via pip:
  ```cmd
  pip install pyusb libusb
  ```

## 2. WebUSB Version ([dji-mic-mo.html](https://github.com/usokawa/dji-mic-mo/blob/main/dji-mic-mo.html))

### Requirements
* **Supported Browsers**: Chromium-based browsers (Chrome, Edge, Opera) on Linux, macOS, and Windows.
  * Mobile (Android / iOS): **Use the official DJI app.** iOS/Safari lacks WebUSB support.
* **Execution Environment**: WebUSB requires a secure context ([HTTPS](https://usokawa.github.io/dji-mic-mo/dji-mic-mo.html) or `localhost`).
  * **Recommended**: Serve via a local web server:
    ```bash
    python -m http.server
    ```
    Then open [http://localhost:8000/dji-mic-mo.html](http://localhost:8000/dji-mic-mo.html).
  * **Alternative**: Opening via `file:///` may work on some setups, but browsers often block USB access.

## Usage

* Python: Run with desired arguments (e.g., `python dji-mic-mo.py --audio_channel stereo`). Check `--help` for details.
* HTML: Open the page, configure settings, and click "Connect Device". Parameters update in real-time.

## FAQ

**Q: Are you affiliated with DJI? Did you steal their secrets?**

A: No.

**Q: Is this tool for eavesdropping?**

A: No.

**Q: Is there any compensation for damages?**

A: No. Read [LICENSE.md](https://github.com/usokawa/dji-mic-mo/blob/main/LICENSE.md).

**Q: What is the confirmed environment?**

A: Python 3.12 and Google Chrome on Linux with DJI Mic Mini Transmitter, Receiver, and DJI Mic Series Mobile Receiver.

**Q: Can I use it on macOS?**

A: Likely yes, but I haven't tested it. [Sponsorships wanted!](https://github.com/sponsors/usokawa)

**Q: Can I use it on Windows?**

A: Yes, but see the OS-Specific USB Setup section for why it's not recommended.

**Q: Does it work with DJI Mic 2/3?**

A: Likely no, but untested. [Sponsorships wanted!](https://github.com/sponsors/usokawa)
