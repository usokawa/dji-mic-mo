import argparse
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field, fields, replace

import usb.core
import usb.util


USB_VENDOR_ID: int = 0x2ca3
USB_PRODUCT_ID: int = 0x4011
USB_ENDPOINT_IN: int = 0x86
USB_ENDPOINT_OUT: int = 0x06
USB_INTERFACE_NUMBER: int = 6

DUML_SOF: int = 0x55
DUML_VERSION: int = 1
DUML_MIN_LENGTH: int = 13
DUML_MAX_LENGTH: int = 0x3ff


def parse_firmware_version(
    data: bytes | bytearray | memoryview, reverse: bool = False
) -> str:
    version_bytes = data[::-1] if reverse else data
    return ".".join(f"{byte:02d}" for byte in version_bytes)


@dataclass(slots=True)
class RxStatus:
    firmware_version: str | None = field(
        default=None, metadata={"label": "Firmware Version"}
    )
    serial_number: str | None = field(
        default=None, metadata={"label": "Serial Number"}
    )
    mac_suffix: str | None = field(
        default=None, metadata={"label": "MAC Suffix"}
    )
    model_name: str | None = field(
        default=None, metadata={"label": "Model Name"}
    )
    battery_level: int | None = field(
        default=None, metadata={"label": "Battery Level (1:Full, 7:Empty)"}
    )
    charging: bool | None = field(
        default=None, metadata={"label": "Charging"}
    )
    stereo: bool | None = field(
        default=None, metadata={"label": "Stereo"}
    )
    safety_track: bool | None = field(
        default=None, metadata={"label": "Safety Track"}
    )
    gain: int | None = field(
        default=None, metadata={"label": "Gain (dB)"}
    )
    monitor_gain: int | None = field(
        default=None, metadata={"label": "Monitor Gain (dB)"}
    )
    clipping_control: bool | None = field(
        default=None, metadata={"label": "Clipping Control"}
    )
    auto_off: bool | None = field(
        default=None, metadata={"label": "Auto Off"}
    )
    receiver_on_off_with_camera: bool | None = field(
        default=None, metadata={"label": "Receiver On/Off With Camera"}
    )
    plug_free_external_speaker: bool | None = field(
        default=None, metadata={"label": "Plug-Free External Speaker"}
    )

    def __str__(self) -> str:
        lines = []
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None:
                lines.append(f"  {f.metadata.get('label', f.name)}: {value}")
        return "\n".join(lines)


@dataclass(slots=True)
class TxStatus:
    tx_id: int | None = field(
        default=None, metadata={"label": "TX ID"}
    )
    firmware_version: str | None = field(
        default=None, metadata={"label": "Firmware Version"}
    )
    serial_number: str | None = field(
        default=None, metadata={"label": "Serial Number"}
    )
    mac_suffix: str | None = field(
        default=None, metadata={"label": "MAC Suffix"}
    )
    model_name: str | None = field(
        default=None, metadata={"label": "Model Name"}
    )
    battery_level: int | None = field(
        default=None, metadata={"label": "Battery Level (1:Full, 7:Empty)"}
    )
    charging: bool | None = field(
        default=None, metadata={"label": "Charging"}
    )
    input_level: int | None = field(
        default=None, metadata={"label": "Input Level"}
    )
    noise_cancellation: bool | None = field(
        default=None, metadata={"label": "Noise Cancellation"}
    )
    strong_noise_cancellation: bool | None = field(
        default=None, metadata={"label": "Strong Noise Cancellation"}
    )
    power_button_for_noise_cancellation: bool | None = field(
        default=None, metadata={"label": "Power Button for Noise Cancellation"}
    )
    low_cut: bool | None = field(
        default=None, metadata={"label": "Low Cut"}
    )
    auto_off: bool | None = field(
        default=None, metadata={"label": "Auto Off"}
    )
    mic_led_off: bool | None = field(
        default=None, metadata={"label": "Mic LED Off"}
    )

    def __str__(self) -> str:
        lines = []
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None and f.name != "tx_id":
                lines.append(f"  {f.metadata.get('label', f.name)}: {value}")
        return "\n".join(lines)


@dataclass(slots=True)
class SystemStatus:
    rx: RxStatus = field(default_factory=RxStatus)
    tx: list[TxStatus] = field(default_factory=lambda: [TxStatus(), TxStatus()])

    def replace(self, **changes) -> 'SystemStatus':
        new_rx = changes.get("rx", replace(self.rx))
        new_tx = changes.get("tx", [replace(t) for t in self.tx])
        return SystemStatus(rx=new_rx, tx=new_tx)

    def __str__(self) -> str:
        tx_blocks = [f"[TX{tx.tx_id}]\n{tx}" for tx in self.tx if tx.tx_id is not None]
        return "\n".join([f"[RX]\n{self.rx}"] + tx_blocks)


class DumlCrc:
    @staticmethod
    def _generate_table(poly: int) -> tuple[int, ...]:
        table = []
        for crc in range(256):
            for _ in range(8):
                crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
            table.append(crc)
        return tuple(table)

    _CRC8_TABLE = _generate_table(0x8c)
    _CRC16_TABLE = _generate_table(0x8408)

    @classmethod
    def calculate8(cls, data: bytes | bytearray | memoryview) -> int:
        crc = 0x77
        for byte in data:
            crc = cls._CRC8_TABLE[crc ^ byte]
        return crc

    @classmethod
    def calculate16(cls, data: bytes | bytearray | memoryview) -> int:
        crc = 0x3692
        for byte in data:
            crc = (crc >> 8) ^ cls._CRC16_TABLE[(crc ^ byte) & 0xff]
        return crc


@dataclass(slots=True)
class DumlPacket:
    version: int
    length: int | None
    sender: int
    receiver: int
    sequence: int
    cmd_type: int
    cmd_set: int
    cmd_id: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        if self.length is None:
            self.length = DUML_MIN_LENGTH + len(self.payload)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> 'DumlPacket':
        length_and_version = int.from_bytes(data[1:3], byteorder="little")
        return cls(
            version=(length_and_version >> 10) & 0x3f,
            length=length_and_version & DUML_MAX_LENGTH,
            sender=data[4],
            receiver=data[5],
            sequence=int.from_bytes(data[6:8], byteorder="little"),
            cmd_type=data[8],
            cmd_set=data[9],
            cmd_id=data[10],
            payload=bytes(data[11:-2])
        )

    def to_bytes(self) -> bytes:
        if self.length > DUML_MAX_LENGTH:
            return b""

        packet = bytearray(self.length)
        view = memoryview(packet)
        length_and_version = (self.length & DUML_MAX_LENGTH) | ((self.version & 0x3f) << 10)

        packet[0] = DUML_SOF
        packet[1:3] = length_and_version.to_bytes(2, "little")
        packet[3] = DumlCrc.calculate8(view[:3])

        packet[4] = self.sender
        packet[5] = self.receiver
        packet[6:8] = self.sequence.to_bytes(2, "little")
        packet[8] = self.cmd_type
        packet[9] = self.cmd_set
        packet[10] = self.cmd_id

        packet[11:11 + len(self.payload)] = self.payload

        crc = DumlCrc.calculate16(view[:self.length - 2])
        packet[self.length - 2:self.length] = crc.to_bytes(2, "little")

        return bytes(packet)

    def __str__(self) -> str:
        lines = [
            f"Ver: {self.version} Len: {self.length}({len(self.payload)}) "
            f"Src: {self.sender:02x} Dst: {self.receiver:02x} "
            f"Seq: {self.sequence:04x} Type: {self.cmd_type:02x} "
            f"Set: {self.cmd_set:02x} ID: {self.cmd_id:02x}"
        ]

        for i in range(0, len(self.payload), 16):
            chunk = self.payload[i:i+16]
            hex_part = chunk[:8].hex(" ")
            if len(chunk) > 8:
                hex_part += "  " + chunk[8:].hex(" ")
            ascii_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in chunk)
            lines.append(f"{i:04x}  {hex_part:<48}  |{ascii_part}|")

        return "\n".join(lines)


class DumlParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def append_buffer(self, data: bytes) -> None:
        self._buffer.extend(data)

    def extract_packets(self) -> list[DumlPacket]:
        packets = []
        offset = 0
        total_bytes = len(self._buffer)

        while offset < total_bytes:
            next_sof_index = self._buffer.find(DUML_SOF, offset)
            if next_sof_index == -1:
                offset = total_bytes
                break
            offset = next_sof_index

            if offset + 4 > total_bytes:
                break

            length_and_version = int.from_bytes(
                self._buffer[offset + 1 : offset + 3], byteorder="little"
            )
            packet_length = length_and_version & DUML_MAX_LENGTH

            if packet_length < DUML_MIN_LENGTH:
                offset += 1
                continue

            if offset + packet_length > total_bytes:
                break

            if DumlCrc.calculate8(self._buffer[offset : offset + 3]) != self._buffer[offset + 3]:
                offset += 1
                continue

            expected_crc = int.from_bytes(
                self._buffer[offset + packet_length - 2 : offset + packet_length],
                byteorder="little"
            )

            if DumlCrc.calculate16(self._buffer[offset : offset + packet_length - 2]) != expected_crc:
                offset += 1
                continue

            packets.append(DumlPacket.from_bytes(
                self._buffer[offset : offset + packet_length]
            ))
            offset += packet_length

        del self._buffer[:offset]
        return packets


class BaseDjiDevice(ABC):
    def __init__(self, usb_device: usb.core.Device, on_packet_sent=None) -> None:
        self.usb_device = usb_device
        self.on_packet_sent = on_packet_sent
        self._sequence_number = 0x1234

    @abstractmethod
    def apply_settings(self, settings: dict[str, int | bool | str]) -> None:
        pass

    @abstractmethod
    def update_status_from_payload(self, payload: bytes, status: SystemStatus) -> None:
        pass

    def set_parameter(self, header: list[int], cmd_id: int, value: int, signed: bool = False) -> None:
        value_byte = value.to_bytes(1, byteorder="little", signed=signed)
        payload = bytes(header) + bytes([cmd_id, 0x00, 0x01]) + value_byte

        packet = DumlPacket(
            version=DUML_VERSION,
            length=None,
            sender=0x02,
            receiver=0x5a,
            sequence=self._sequence_number,
            cmd_type=0x40,
            cmd_set=0x5b,
            cmd_id=0x01,
            payload=payload
        )

        self._sequence_number = (self._sequence_number + 1) & 0xffff

        packet_bytes = packet.to_bytes()

        if packet_bytes:
            with suppress(usb.core.USBError):
                self.usb_device.write(USB_ENDPOINT_OUT, packet_bytes, timeout=1000)
                if self.on_packet_sent:
                    self.on_packet_sent(packet)


class MobileRxDevice(BaseDjiDevice):
    def apply_settings(self, settings: dict[str, int | bool | str]) -> None:
        rx_header = [0x02, 0x00, 0x00, 0x00, 0x00]
        tx_header = [0x02, 0xff, 0xff, 0x00, 0x00]

        for key, value in settings.items():
            match key:
                case "audio_channel":
                    self.set_parameter(rx_header, 0x21, 0x01 if value == "safety_track" else 0x00)
                    self.set_parameter(rx_header, 0x08, 0x02 if value == "stereo" else 0x00)
                case "clipping_control":
                    self.set_parameter(rx_header, 0x1e, 0x01 if value else 0x00)
                case "plug_free_external_speaker":
                    self.set_parameter(rx_header, 0x23, 0x01 if value else 0x00)
                case "monitor_gain":
                    self.set_parameter(rx_header, 0x26, value, signed=True)
                case "gain":
                    self.set_parameter(rx_header, 0x39, value, signed=True)
                case "low_cut":
                    self.set_parameter(tx_header, 0x03, 0x01 if value else 0x00)
                case "mic_led_off":
                    self.set_parameter(tx_header, 0x0a, 0x02 if value else 0x00)
                case "auto_off_tx":
                    self.set_parameter(tx_header, 0x10, 0x01 if value else 0x00)

    def update_status_from_payload(self, payload: bytes, status: SystemStatus) -> None:
        payload_view = memoryview(payload)
        payload_length = len(payload_view)
        if payload_length < 4 or payload_view[1] + 3 != payload_length:
            return

        match payload_view[3]:
            case 0x01 if payload_length >= 0x3b:
                status.tx[0].tx_id = None
                status.tx[1].tx_id = None
                rx = status.rx

                if payload_view[8] == 0x12:
                    rx.firmware_version = parse_firmware_version(
                        payload_view[9:13], reverse=True
                    )
                    rx.serial_number = payload_view[13:27].tobytes().decode("ascii", errors="replace")
                if payload_view[32] == 0x06:
                    rx.mac_suffix = payload_view[33:39].tobytes().decode("ascii", errors="replace")
                if payload_view[44] == 0x0e:
                    rx.model_name = payload_view[45:59].tobytes().decode("ascii", errors="replace")

                for offset in range(59, payload_length - 53, 54):
                    tx_id = payload_view[offset + 1]
                    if payload_view[offset] == 0x01 and tx_id in (1, 2):
                        tx = status.tx[tx_id - 1]
                        tx.tx_id = tx_id

                        if payload_view[offset + 5] == 0x12:
                            tx.firmware_version = parse_firmware_version(
                                payload_view[offset + 6 : offset + 10], reverse=True
                            )
                            tx.serial_number = payload_view[offset + 10 : offset + 24].tobytes().decode("ascii", errors="replace")
                        if payload_view[offset + 29] == 0x06:
                            tx.mac_suffix = payload_view[offset + 30 : offset + 36].tobytes().decode("ascii", errors="replace")
                        if payload_view[offset + 41] == 0x0c:
                            tx.model_name = payload_view[offset + 42 : offset + 54].tobytes().decode("ascii", errors="replace")

            case 0x03 if payload_length >= 0x29:
                status.tx[0].tx_id = None
                status.tx[1].tx_id = None
                rx = status.rx

                flags10 = payload_view[10]
                flags37 = payload_view[37]

                rx.stereo = bool(flags10 & 0x04)
                rx.gain = int.from_bytes(payload_view[11:12], signed=True)
                rx.monitor_gain = int.from_bytes(payload_view[16:17], signed=True)
                rx.safety_track = bool(flags37 & 0x40)
                rx.clipping_control = bool(flags37 & 0x10)
                rx.plug_free_external_speaker = bool(flags37 & 0x02)

                for offset in range(41, payload_length - 31, 32):
                    tx_id = payload_view[offset + 1]
                    if payload_view[offset] == 0x02 and tx_id in (1, 2):
                        tx = status.tx[tx_id - 1]
                        tx.tx_id = tx_id

                        flags6 = payload_view[offset + 6]
                        flags7 = payload_view[offset + 7]
                        flags9 = payload_view[offset + 9]

                        tx.strong_noise_cancellation = bool(flags6 & 0x20)
                        tx.auto_off = bool(flags6 & 0x10)
                        tx.mic_led_off = bool(flags6 & 0x02)
                        tx.battery_level = (flags7 >> 2) & 0x07
                        tx.charging = bool(flags7 & 0x02)
                        tx.noise_cancellation = bool(flags7 & 0x01)
                        tx.low_cut = bool(flags9 & 0x20)

            case 0x05 if payload_length >= 0x0a:
                for offset in range(3, payload_length - 6, 7):
                    tx_id = payload_view[offset + 1]
                    if payload_view[offset] == 0x05 and tx_id in (1, 2):
                        tx = status.tx[tx_id - 1]
                        tx.tx_id = tx_id
                        tx.input_level = payload_view[offset + 6]


class MiniRxDevice(BaseDjiDevice):
    def apply_settings(self, settings: dict[str, int | bool | str]) -> None:
        rx_header = [0x00, 0x00]
        tx_header = [0x00, 0x03]

        for key, value in settings.items():
            match key:
                case "audio_channel":
                    self.set_parameter(rx_header, 0x21, 0x01 if value == "safety_track" else 0x00)
                    self.set_parameter(rx_header, 0x08, 0x02 if value == "stereo" else 0x00)
                case "auto_off_rx":
                    self.set_parameter(rx_header, 0x10, 0x01 if value else 0x00)
                case "clipping_control":
                    self.set_parameter(rx_header, 0x1e, 0x01 if value else 0x00)
                case "receiver_on_off_with_camera":
                    self.set_parameter(rx_header, 0x20, 0x01 if value else 0x00)
                case "plug_free_external_speaker":
                    self.set_parameter(rx_header, 0x23, 0x01 if value else 0x00)
                case "low_cut":
                    self.set_parameter(tx_header, 0x03, 0x01 if value else 0x00)
                case "mic_led_off":
                    self.set_parameter(tx_header, 0x0a, 0x02 if value else 0x00)
                case "power_button_for_noise_cancellation":
                    self.set_parameter(tx_header, 0x0f, 0x01 if value else 0x00)
                case "auto_off_tx":
                    self.set_parameter(tx_header, 0x10, 0x01 if value else 0x00)
                case "strong_noise_cancellation":
                    self.set_parameter(tx_header, 0x1d, 0x01 if value else 0x00)

    def update_status_from_payload(self, payload: bytes, status: SystemStatus) -> None:
        payload_view = memoryview(payload)
        payload_length = len(payload_view)
        if payload_length < 2 or payload_view[1] != payload_length:
            return

        offset = 3

        for tx_count in range(2):
            if (
                offset + 9 <= payload_length
                and payload_view[offset + 1] == 0x40
                and payload_view[offset + 2] == 0x00
            ):
                status.tx[tx_count].tx_id = None
                offset += 9
            elif offset + 23 <= payload_length and payload_view[offset + 8] == 0x0e:
                tx = status.tx[tx_count]
                tx.tx_id = tx_count + 1

                tx.firmware_version = parse_firmware_version(
                    payload_view[offset + 4 : offset + 8]
                )
                tx.serial_number = payload_view[offset + 9 : offset + 23].tobytes().decode("ascii", errors="replace")

                flags0 = payload_view[offset]
                flags1 = payload_view[offset + 1]
                flags3 = payload_view[offset + 3]

                tx.power_button_for_noise_cancellation = bool(flags0 & 0x80)
                tx.strong_noise_cancellation = bool(flags0 & 0x20)
                tx.auto_off = bool(flags0 & 0x10)
                tx.low_cut = bool(flags0 & 0x04)
                tx.battery_level = (flags1 >> 2) & 0x07
                tx.charging = bool(flags1 & 0x02)
                tx.noise_cancellation = bool(flags1 & 0x01)
                tx.input_level = payload_view[offset + 2]
                tx.mic_led_off = bool(flags3 & 0x80)

                offset += 23

        if offset + 22 <= payload_length and payload_view[offset + 6] == 0x0e:
            rx = status.rx

            rx.firmware_version = parse_firmware_version(
                payload_view[offset + 2 : offset + 6]
            )
            rx.serial_number = payload_view[offset + 7 : offset + 21].tobytes().decode("ascii", errors="replace")

            flags0 = payload_view[offset]
            flags1 = payload_view[offset + 1]
            flags21 = payload_view[offset + 21]

            rx.battery_level = (flags0 >> 5) & 0x07
            rx.charging = bool(flags0 & 0x10)
            rx.stereo = bool(flags0 & 0x08)
            rx.auto_off = bool(flags0 & 0x02)
            rx.receiver_on_off_with_camera = bool(flags0 & 0x01)
            rx.safety_track = bool(flags1 & 0x80)
            rx.clipping_control = bool(flags1 & 0x20)
            rx.plug_free_external_speaker = bool(flags21 & 0x01)


class DjiMicManager:
    def __init__(self, usb_device: usb.core.Device,
                 on_packet_received=None,
                 on_packet_sent=None,
                 on_status_update=None) -> None:
        self.usb_device = usb_device
        self.on_packet_received = on_packet_received
        self.on_packet_sent = on_packet_sent
        self.on_status_update = on_status_update

        product_name = get_product_name(usb_device)

        if product_name == "Wireless Mic Rx":
            self.active_device = MobileRxDevice(usb_device, on_packet_sent=self.on_packet_sent)
        elif product_name == "DJI MIC MINI":
            self.active_device = MiniRxDevice(usb_device, on_packet_sent=self.on_packet_sent)
        else:
            raise ValueError(f"Unsupported product: {product_name}")

        self.status = SystemStatus()
        self.duml_parser = DumlParser()

    def start_monitoring(self, settings: dict[str, int | bool | str]) -> None:
        with suppress(NotImplementedError, usb.core.USBError):
            if self.usb_device.is_kernel_driver_active(USB_INTERFACE_NUMBER):
                self.usb_device.detach_kernel_driver(USB_INTERFACE_NUMBER)

        usb.util.claim_interface(self.usb_device, USB_INTERFACE_NUMBER)
        self.apply_ordered_settings(settings)

        if "plug_free_external_speaker" in settings:
            return

        try:
            with suppress(KeyboardInterrupt, usb.core.USBError):
                while True:
                    self._poll_usb_device()
        finally:
            with suppress(usb.core.USBError):
                usb.util.release_interface(self.usb_device, USB_INTERFACE_NUMBER)

    def apply_ordered_settings(self, settings: dict[str, int | bool | str]) -> None:
        ordered_settings = settings.copy()
        if "plug_free_external_speaker" in ordered_settings:
            ordered_settings["plug_free_external_speaker"] = ordered_settings.pop(
                "plug_free_external_speaker"
            )
        self.active_device.apply_settings(ordered_settings)

    def _poll_usb_device(self) -> None:
        try:
            chunk = self.usb_device.read(USB_ENDPOINT_IN, 1024, timeout=1000)
        except usb.core.USBTimeoutError:
            return
        except usb.core.USBError as error:
            if error.errno not in (110, 10060, 60):
                raise
            return

        self.duml_parser.append_buffer(chunk.tobytes())

        for packet in self.duml_parser.extract_packets():
            if self.on_packet_received:
                self.on_packet_received(packet)

            if packet.cmd_set == 0x5b and packet.cmd_id == 0x03:
                new_status = self.status.replace()
                self.active_device.update_status_from_payload(packet.payload, new_status)
                if self.status != new_status:
                    self.status = new_status
                    if self.on_status_update:
                        self.on_status_update(self.status)


def get_product_name(device: usb.core.Device) -> str:
    with suppress(ValueError, usb.core.USBError):
        return device.product
    with suppress(ValueError, usb.core.USBError):
        return usb.util.get_string(device, device.iProduct)
    return "Unknown"


def get_target_usb_device(target_id: str | None = None) -> usb.core.Device | None:
    devices = list(
        usb.core.find(find_all=True, idVendor=USB_VENDOR_ID, idProduct=USB_PRODUCT_ID)
    )

    if not devices:
        return None

    if len(devices) == 1 and target_id is None:
        return devices[0]

    if target_id:
        for device in devices:
            if f"{device.bus}:{device.address}" == target_id:
                return device
        raise ValueError(f"Device '{target_id}' not found.")

    devices.sort(key=lambda d: (d.bus, d.address))
    device_list = "\n".join(
        f"{d.bus}:{d.address} - {get_product_name(d)}" for d in devices
    )

    raise ValueError(
        f"Multiple devices found. Specify one using --device:\n{device_list}"
    )


class FilePacketLogger:
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.log_file = None

    def __enter__(self):
        self.log_file = open(self.file_path, "w", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.log_file:
            self.log_file.close()

    def log_packet(self, packet: DumlPacket) -> None:
        if self.log_file:
            self.log_file.write(f"{packet}\n\n")
            self.log_file.flush()


def _print_status(status: SystemStatus) -> None:
    print(f"\033[H\033[J{status}", end="", flush=True)


def parse_cli_arguments() -> dict:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--device",
        type=str
    )
    parser.add_argument(
        "--debug",
        type=str
    )

    rx_group = parser.add_argument_group("RX Settings")
    rx_group.add_argument(
        "--audio-channel",
        choices=["stereo", "mono", "safety_track"],
        help="[Mobile RX, Mic Mini RX]"
    )
    rx_group.add_argument(
        "--gain",
        type=int,
        choices=[-12, -6, 0, 6, 12],
        help="[Mobile RX]"
    )
    rx_group.add_argument(
        "--monitor-gain",
        type=int,
        choices=range(-12, 13),
        metavar="[-12...12]",
        help="[Mobile RX]"
    )
    rx_group.add_argument(
        "--clipping-control",
        action=argparse.BooleanOptionalAction,
        help="[Mobile RX, Mic Mini RX]"
    )
    rx_group.add_argument(
        "--auto-off-rx",
        action=argparse.BooleanOptionalAction,
        help="[Mic Mini RX]"
    )
    rx_group.add_argument(
        "--receiver-on-off-with-camera",
        action=argparse.BooleanOptionalAction,
        help="[Mic Mini RX]"
    )
    rx_group.add_argument(
        "--plug-free-external-speaker",
        action=argparse.BooleanOptionalAction,
        help="[Mobile RX, Mic Mini RX] (Restart required)"
    )

    tx_group = parser.add_argument_group("TX Settings")
    tx_group.add_argument(
        "--strong-noise-cancellation",
        action=argparse.BooleanOptionalAction,
        help="[Mic Mini RX]"
    )
    tx_group.add_argument(
        "--power-button-for-noise-cancellation",
        action=argparse.BooleanOptionalAction,
        help="[Mic Mini RX]"
    )
    tx_group.add_argument(
        "--low-cut",
        action=argparse.BooleanOptionalAction,
        help="[Mobile RX, Mic Mini RX]"
    )
    tx_group.add_argument(
        "--auto-off-tx",
        action=argparse.BooleanOptionalAction,
        help="[Mobile RX, Mic Mini RX]"
    )
    tx_group.add_argument(
        "--mic-led-off",
        action=argparse.BooleanOptionalAction,
        help="[Mobile RX, Mic Mini RX]"
    )

    args = parser.parse_args()
    return {key: value for key, value in vars(args).items() if value is not None}


class DjiMicCLIController:
    def __init__(self, args: dict) -> None:
        self._target_id = args.pop("device", None)
        self._debug_file_path = args.pop("debug", None)
        self._settings = args
        self._manager = None

    def run(self) -> None:
        try:
            target_usb_device = get_target_usb_device(self._target_id)

            if target_usb_device is None:
                print("Device not found.")
                return

            if self._debug_file_path:
                with FilePacketLogger(self._debug_file_path) as logger:
                    self._manager = DjiMicManager(
                        target_usb_device,
                        on_packet_received=logger.log_packet,
                        on_packet_sent=logger.log_packet,
                        on_status_update=_print_status
                    )
                    self._manager.start_monitoring(self._settings)
            else:
                self._manager = DjiMicManager(
                    target_usb_device,
                    on_status_update=_print_status
                )
                self._manager.start_monitoring(self._settings)

        except ValueError as error:
            print(error)
        except usb.core.USBError as error:
            print(error)


def main() -> None:
    args = parse_cli_arguments()
    controller = DjiMicCLIController(args)
    controller.run()


if __name__ == "__main__":
    main()
