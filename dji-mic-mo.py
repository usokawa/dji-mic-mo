import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from typing import Any, Callable

import usb.core
import usb.util


USB_VENDOR_ID = 0x2CA3
USB_PRODUCT_ID = 0x4011
USB_ENDPOINT_IN = 0x86
USB_ENDPOINT_OUT = 0x06
USB_INTERFACE_NUMBER = 6

DUML_SOF = 0x55
DUML_VERSION = 1
DUML_MIN_LENGTH = 13
DUML_MAX_LENGTH = 0x3FF


def generate_crc_table(poly: int) -> tuple[int, ...]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


CRC8_TABLE = generate_crc_table(0x8C)
CRC16_TABLE = generate_crc_table(0x8408)


def calculate_crc8(data: bytes) -> int:
    crc = 0x77
    for byte in data:
        crc = CRC8_TABLE[crc ^ byte]
    return crc


def calculate_crc16(data: bytes) -> int:
    crc = 0x3692
    for byte in data:
        crc = (crc >> 8) ^ CRC16_TABLE[(crc ^ byte) & 0xFF]
    return crc


def parse_ascii_string(data: bytes) -> str:
    return data.decode("ascii", errors="ignore").rstrip("\x00")


def parse_firmware_version(data: bytes, reverse: bool = False) -> str:
    sequence_data = reversed(data) if reverse else data
    return ".".join(f"{byte:02d}" for byte in sequence_data)


@dataclass
class RxStatus:
    firmware_version: str | None = field(default=None, metadata={"name": "Firmware Version"})
    serial_number: str | None = field(default=None, metadata={"name": "Serial Number"})
    mac_suffix: str | None = field(default=None, metadata={"name": "MAC Suffix"})
    model_name: str | None = field(default=None, metadata={"name": "Model Name"})
    battery_level: int | None = field(default=None, metadata={"name": "Battery Level (1:Full, 7:Empty)"})
    charging: bool | None = field(default=None, metadata={"name": "Charging"})
    gain: int | None = field(default=None, metadata={"name": "Gain (dB)"})
    monitor_gain: int | None = field(default=None, metadata={"name": "Monitor Gain (dB)"})
    stereo: bool | None = field(default=None, metadata={"name": "Stereo"})
    safety_track: bool | None = field(default=None, metadata={"name": "Safety Track"})
    clipping_control: bool | None = field(default=None, metadata={"name": "Clipping Control"})
    auto_off: bool | None = field(default=None, metadata={"name": "Auto Off"})
    receiver_on_off_with_camera: bool | None = field(default=None, metadata={"name": "Receiver On/Off With Camera"})
    plug_free_external_speaker: bool | None = field(default=None, metadata={"name": "Plug-Free External Speaker"})

    def __str__(self) -> str:
        lines = []
        for f in fields(self):
            val = getattr(self, f.name)
            if val is not None:
                name = f.metadata.get("name", f.name)
                lines.append(f"  {name}: {val}")
        return "\n".join(lines)


@dataclass
class TxStatus:
    tx_id: int | None = field(default=None, metadata={"name": "TX ID"})
    firmware_version: str | None = field(default=None, metadata={"name": "Firmware Version"})
    serial_number: str | None = field(default=None, metadata={"name": "Serial Number"})
    mac_suffix: str | None = field(default=None, metadata={"name": "MAC Suffix"})
    model_name: str | None = field(default=None, metadata={"name": "Model Name"})
    battery_level: int | None = field(default=None, metadata={"name": "Battery Level (1:Full, 7:Empty)"})
    charging: bool | None = field(default=None, metadata={"name": "Charging"})
    input_level: int | None = field(default=None, metadata={"name": "Input Level"})
    noise_cancellation: bool | None = field(default=None, metadata={"name": "Noise Cancellation"})
    strong_noise_cancellation: bool | None = field(default=None, metadata={"name": "Strong Noise Cancellation"})
    power_button_for_noise_cancellation: bool | None = field(default=None, metadata={"name": "Power Button for Noise Cancellation"})
    low_cut: bool | None = field(default=None, metadata={"name": "Low Cut"})
    auto_off: bool | None = field(default=None, metadata={"name": "Auto Off"})
    mic_led_off: bool | None = field(default=None, metadata={"name": "Mic LED Off"})

    def __str__(self) -> str:
        lines = []
        for f in fields(self):
            val = getattr(self, f.name)
            if val is not None and f.name != "tx_id":
                name = f.metadata.get("name", f.name)
                lines.append(f"  {name}: {val}")
        return "\n".join(lines)


@dataclass
class SystemStatus:
    rx: RxStatus = field(default_factory=RxStatus)
    tx: list[TxStatus] = field(default_factory=lambda: [TxStatus(), TxStatus()])

    def __str__(self) -> str:
        blocks = [f"[RX]\n{self.rx}"]
        for tx in self.tx:
            if tx.tx_id is not None:
                blocks.append(f"[TX{tx.tx_id}]\n{tx}")
        return "\n".join(blocks)


@dataclass
class DumlPacket:
    version: int
    length: int
    sender: int
    receiver: int
    sequence: int
    cmd_type: int
    cmd_set: int
    cmd_id: int
    payload: bytes = b''

    def __post_init__(self):
        if self.length == 0:
            self.length = DUML_MIN_LENGTH + len(self.payload)

    def to_bytes(self) -> bytes:
        if self.length > DUML_MAX_LENGTH:
            return b''

        length_and_version = (self.length & 0x3FF) | ((self.version & 0x3F) << 10)
        header = bytearray([DUML_SOF, length_and_version & 0xFF, (length_and_version >> 8) & 0xFF])
        header.append(calculate_crc8(header))

        body = bytearray([
            self.sender, self.receiver,
            self.sequence & 0xFF, (self.sequence >> 8) & 0xFF,
            self.cmd_type, self.cmd_set, self.cmd_id
        ])

        packet = header + body + self.payload
        crc = calculate_crc16(packet)
        packet.extend([crc & 0xFF, (crc >> 8) & 0xFF])

        return bytes(packet)


class DumlParser:
    def __init__(self):
        self.buffer = b''

    def append_buffer(self, data: bytes) -> None:
        self.buffer += data

    def extract_packets(self) -> list[DumlPacket]:
        packets = []
        offset = 0
        total_bytes = len(self.buffer)

        while offset < total_bytes:
            if self.buffer[offset] != DUML_SOF:
                offset += 1
                continue

            if offset + 4 > total_bytes:
                break

            length_and_version = self.buffer[offset + 1] | (self.buffer[offset + 2] << 8)
            packet_length = length_and_version & 0x3FF
            packet_version = (length_and_version >> 10) & 0x3F

            if packet_length < DUML_MIN_LENGTH:
                offset += 1
                continue

            if offset + packet_length > total_bytes:
                break

            header = self.buffer[offset:offset + 3]
            if calculate_crc8(header) != self.buffer[offset + 3]:
                offset += 1
                continue

            packet_data = self.buffer[offset:offset + packet_length]
            expected_crc = int.from_bytes(packet_data[-2:], byteorder="little")

            if calculate_crc16(packet_data[:-2]) != expected_crc:
                offset += 1
                continue

            packets.append(DumlPacket(
                version=packet_version,
                length=packet_length,
                sender=packet_data[4],
                receiver=packet_data[5],
                sequence=int.from_bytes(packet_data[6:8], byteorder="little"),
                cmd_type=packet_data[8],
                cmd_set=packet_data[9],
                cmd_id=packet_data[10],
                payload=bytes(packet_data[11:-2])
            ))
            offset += packet_length

        self.buffer = self.buffer[offset:]
        return packets


class AbstractDjiDevice(ABC):
    def __init__(self, usb_device: usb.core.Device, on_packet_sent: Callable[['DumlPacket'], None] | None = None):
        self.usb_device = usb_device
        self.on_packet_sent = on_packet_sent
        self.sequence_number = 0x1234

    @abstractmethod
    def apply_configuration(self, configuration: dict[str, Any]) -> None:
        pass

    @abstractmethod
    def parse_status_payload(self, payload: bytes, system_status: SystemStatus) -> None:
        pass

    def set_parameter(self, header: list[int], cmd_id: int, value: int) -> None:
        payload = bytes(header + [cmd_id, 0x00, 0x01, value])

        packet = DumlPacket(
            version=DUML_VERSION,
            length=0,
            sender=0x02,
            receiver=0x5A,
            sequence=self.sequence_number,
            cmd_type=0x40,
            cmd_set=0x5B,
            cmd_id=0x01,
            payload=payload
        )

        self.sequence_number = (self.sequence_number + 1) & 0xFFFF

        if self.on_packet_sent:
            self.on_packet_sent(packet)

        packet_bytes = packet.to_bytes()

        if packet_bytes:
            try:
                self.usb_device.write(USB_ENDPOINT_OUT, packet_bytes, timeout=1000)
            except usb.core.USBError:
                pass


class MobileRxDevice(AbstractDjiDevice):
    def apply_configuration(self, configuration: dict[str, Any]) -> None:
        header1 = [0x02, 0x00, 0x00, 0x00, 0x00]
        header2 = [0x02, 0xff, 0xff, 0x00, 0x00]

        for key, value in configuration.items():
            match key:
                case "audio_channel":
                    self.set_parameter(header1, 0x21, 0x01 if value == "safety_track" else 0x00)
                    self.set_parameter(header1, 0x08, 0x02 if value == "stereo" else 0x00)
                case "clipping_control":
                    self.set_parameter(header1, 0x1e, 0x01 if value else 0x00)
                case "plug_free_external_speaker":
                    self.set_parameter(header1, 0x23, 0x01 if value else 0x00)
                case "monitor_gain":
                    self.set_parameter(header1, 0x26, value & 0xFF)
                case "gain":
                    self.set_parameter(header1, 0x39, value & 0xFF)
                case "low_cut":
                    self.set_parameter(header2, 0x03, 0x01 if value else 0x00)
                case "mic_led_off":
                    self.set_parameter(header2, 0x0a, 0x02 if value else 0x00)
                case "auto_off_tx":
                    self.set_parameter(header2, 0x10, 0x01 if value else 0x00)

    def parse_status_payload(self, payload: bytes, system_status: SystemStatus) -> None:
        payload_length = len(payload)
        if payload_length < 4 or payload[1] + 3 != payload_length:
            return

        match payload[3]:
            case 0x01 if payload_length >= 0x3B:
                system_status.tx[0].tx_id = None
                system_status.tx[1].tx_id = None
                rx = system_status.rx

                if payload[8] == 0x12:
                    rx.firmware_version = parse_firmware_version(payload[9:13], reverse=True)
                    rx.serial_number = parse_ascii_string(payload[13:27])
                if payload[32] == 0x06:
                    rx.mac_suffix = parse_ascii_string(payload[33:39])
                if payload[44] == 0x0e:
                    rx.model_name = parse_ascii_string(payload[45:59])

                for offset in range(59, payload_length - 53, 54):
                    b1 = payload[offset + 1]
                    if payload[offset] == 0x01 and b1 in (1, 2):
                        tx = system_status.tx[b1 - 1]
                        tx.tx_id = b1

                        if payload[offset + 5] == 0x12:
                            tx.firmware_version = parse_firmware_version(payload[offset + 6:offset + 10], reverse=True)
                            tx.serial_number = parse_ascii_string(payload[offset + 10:offset + 24])
                        if payload[offset + 29] == 0x06:
                            tx.mac_suffix = parse_ascii_string(payload[offset + 30:offset + 36])
                        if payload[offset + 41] == 0x0c:
                            tx.model_name = parse_ascii_string(payload[offset + 42:offset + 54])

            case 0x03 if payload_length >= 0x29:
                system_status.tx[0].tx_id = None
                system_status.tx[1].tx_id = None
                rx = system_status.rx

                flags10 = payload[10]
                flags37 = payload[37]

                rx.stereo = bool(flags10 & 0x04)
                rx.gain = int.from_bytes(payload[11:12], byteorder="little", signed=True)
                rx.monitor_gain = int.from_bytes(payload[16:17], byteorder="little", signed=True)
                rx.safety_track = bool(flags37 & 0x40)
                rx.clipping_control = bool(flags37 & 0x10)
                rx.plug_free_external_speaker = bool(flags37 & 0x02)

                for offset in range(41, payload_length - 31, 32):
                    b1 = payload[offset + 1]
                    if payload[offset] == 0x02 and b1 in (1, 2):
                        tx = system_status.tx[b1 - 1]
                        tx.tx_id = b1

                        flags6 = payload[offset + 6]
                        flags7 = payload[offset + 7]
                        flags9 = payload[offset + 9]

                        tx.strong_noise_cancellation = bool(flags6 & 0x20)
                        tx.auto_off = bool(flags6 & 0x10)
                        tx.mic_led_off = bool(flags6 & 0x02)
                        tx.battery_level = (flags7 >> 2) & 0x07
                        tx.charging = bool(flags7 & 0x02)
                        tx.noise_cancellation = bool(flags7 & 0x01)
                        tx.low_cut = bool(flags9 & 0x20)

            case 0x05 if payload_length >= 0x0A:
                for offset in range(3, payload_length - 6, 7):
                    b1 = payload[offset + 1]
                    if payload[offset] == 0x05 and b1 in (1, 2):
                        tx = system_status.tx[b1 - 1]
                        tx.tx_id = b1
                        tx.input_level = payload[offset + 6]


class MiniRxDevice(AbstractDjiDevice):
    def apply_configuration(self, configuration: dict[str, Any]) -> None:
        header1 = [0x00, 0x00]
        header2 = [0x00, 0x03]

        for key, value in configuration.items():
            match key:
                case "audio_channel":
                    self.set_parameter(header1, 0x21, 0x01 if value == "safety_track" else 0x00)
                    self.set_parameter(header1, 0x08, 0x02 if value == "stereo" else 0x00)
                case "auto_off_rx":
                    self.set_parameter(header1, 0x10, 0x01 if value else 0x00)
                case "clipping_control":
                    self.set_parameter(header1, 0x1e, 0x01 if value else 0x00)
                case "receiver_on_off_with_camera":
                    self.set_parameter(header1, 0x20, 0x01 if value else 0x00)
                case "plug_free_external_speaker":
                    self.set_parameter(header1, 0x23, 0x01 if value else 0x00)
                case "low_cut":
                    self.set_parameter(header2, 0x03, 0x01 if value else 0x00)
                case "mic_led_off":
                    self.set_parameter(header2, 0x0a, 0x02 if value else 0x00)
                case "power_button_for_noise_cancellation":
                    self.set_parameter(header2, 0x0f, 0x01 if value else 0x00)
                case "auto_off_tx":
                    self.set_parameter(header2, 0x10, 0x01 if value else 0x00)
                case "strong_noise_cancellation":
                    self.set_parameter(header2, 0x1d, 0x01 if value else 0x00)

    def parse_status_payload(self, payload: bytes, system_status: SystemStatus) -> None:
        payload_length = len(payload)
        if payload_length < 2 or payload[1] != payload_length:
            return

        tx_count = 0
        offset = 3

        while offset < payload_length:
            if tx_count < 2:
                if offset + 9 <= payload_length and payload[offset + 1:offset + 3] == b'\x40\x00':
                    system_status.tx[tx_count].tx_id = None
                    tx_count += 1
                    offset += 9
                    continue

                if offset + 23 <= payload_length and payload[offset + 8] == 0x0e:
                    tx = system_status.tx[tx_count]
                    tx.tx_id = tx_count + 1

                    tx.firmware_version = parse_firmware_version(payload[offset + 4:offset + 8])
                    tx.serial_number = parse_ascii_string(payload[offset + 9:offset + 23])

                    flags0 = payload[offset]
                    flags1 = payload[offset + 1]
                    flags3 = payload[offset + 3]

                    tx.power_button_for_noise_cancellation = bool(flags0 & 0x80)
                    tx.strong_noise_cancellation = bool(flags0 & 0x20)
                    tx.auto_off = bool(flags0 & 0x10)
                    tx.low_cut = bool(flags0 & 0x04)
                    tx.battery_level = (flags1 >> 2) & 0x07
                    tx.charging = bool(flags1 & 0x02)
                    tx.noise_cancellation = bool(flags1 & 0x01)
                    tx.input_level = payload[offset + 2]
                    tx.mic_led_off = bool(flags3 & 0x80)

                    tx_count += 1
                    offset += 23
                    continue

            if offset + 22 <= payload_length and payload[offset + 6] == 0x0e:
                rx = system_status.rx

                rx.firmware_version = parse_firmware_version(payload[offset + 2:offset + 6])
                rx.serial_number = parse_ascii_string(payload[offset + 7:offset + 21])

                flags0 = payload[offset]
                flags1 = payload[offset + 1]
                flags21 = payload[offset + 21]

                rx.battery_level = (flags0 >> 5) & 0x07
                rx.charging = bool(flags0 & 0x10)
                rx.stereo = bool(flags0 & 0x08)
                rx.auto_off = bool(flags0 & 0x02)
                rx.receiver_on_off_with_camera = bool(flags0 & 0x01)
                rx.safety_track = bool(flags1 & 0x80)
                rx.clipping_control = bool(flags1 & 0x20)
                rx.plug_free_external_speaker = bool(flags21 & 0x01)
                break

            break


class DjiMicManager:
    def __init__(self, usb_device: usb.core.Device,
                 on_packet_received: Callable[['DumlPacket'], None] | None = None,
                 on_status_update: Callable[['SystemStatus'], None] | None = None):
        self.usb_device = usb_device
        self.on_packet_received = on_packet_received
        self.on_status_update = on_status_update

        try:
            product_name = usb_device.product
        except (ValueError, usb.core.USBError):
            product_name = usb.util.get_string(usb_device, usb_device.iProduct)

        if product_name == "Wireless Mic Rx":
            self.active_device = MobileRxDevice(usb_device, on_packet_sent=self.on_packet_received)
        elif product_name == "DJI MIC MINI":
            self.active_device = MiniRxDevice(usb_device, on_packet_sent=self.on_packet_received)
        else:
            raise ValueError(f"Unsupported product: {product_name}")

        self.system_status = SystemStatus()
        self.duml_parser = DumlParser()

    def start_monitoring(self, configuration: dict[str, Any]) -> None:
        try:
            if self.usb_device.is_kernel_driver_active(USB_INTERFACE_NUMBER):
                self.usb_device.detach_kernel_driver(USB_INTERFACE_NUMBER)
        except NotImplementedError:
            pass

        usb.util.claim_interface(self.usb_device, USB_INTERFACE_NUMBER)
        self.apply_ordered_configuration(configuration)

        try:
            if "plug_free_external_speaker" in configuration:
                return

            while True:
                self._poll_usb_device()
        except KeyboardInterrupt:
            pass
        finally:
            usb.util.release_interface(self.usb_device, USB_INTERFACE_NUMBER)

    def apply_ordered_configuration(self, configuration: dict[str, Any]) -> None:
        ordered_configuration = configuration.copy()
        if "plug_free_external_speaker" in ordered_configuration:
            ordered_configuration["plug_free_external_speaker"] = ordered_configuration.pop("plug_free_external_speaker")
        self.active_device.apply_configuration(ordered_configuration)

    def _poll_usb_device(self) -> None:
        try:
            received_chunk = self.usb_device.read(USB_ENDPOINT_IN, 1024, timeout=1000)
            self.duml_parser.append_buffer(received_chunk.tobytes())

            for packet in self.duml_parser.extract_packets():
                if self.on_packet_received:
                    self.on_packet_received(packet)

                if packet.cmd_set == 0x5B and packet.cmd_id == 0x03:
                    self.active_device.parse_status_payload(packet.payload, self.system_status)
                    if self.on_status_update:
                        self.on_status_update(self.system_status)

        except usb.core.USBTimeoutError:
            pass
        except usb.core.USBError as error:
            if error.errno not in (110, 10060, 60):
                raise


def format_packet_dump(packet: DumlPacket) -> str:
    payload_length = len(packet.payload)
    lines = [
        f"Ver: {packet.version} Len: {packet.length}({payload_length}) "
        f"Src: {packet.sender:02x} Dst: {packet.receiver:02x} "
        f"Seq: {packet.sequence:04x} Type: {packet.cmd_type:02x} "
        f"Set: {packet.cmd_set:02x} ID: {packet.cmd_id:02x}"
    ]
    for i in range(0, len(packet.payload), 16):
        chunk = packet.payload[i:i+16]
        hex_bytes = [f"{b:02x}" for b in chunk]
        if len(hex_bytes) > 8:
            hex_part = " ".join(hex_bytes[:8]) + "  " + " ".join(hex_bytes[8:])
        else:
            hex_part = " ".join(hex_bytes)
        ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{i:04x}  {hex_part:<48}  |{ascii_part}|")
    return "\n".join(lines)


class FilePacketLogger:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.log_file = None

    def __enter__(self):
        self.log_file = open(self.file_path, "w", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.log_file:
            self.log_file.close()

    def log_packet(self, packet: DumlPacket) -> None:
        if self.log_file:
            self.log_file.write(format_packet_dump(packet) + "\n\n")
            self.log_file.flush()


def display_system_status(status: SystemStatus) -> None:
    print(f"\033[H\033[J{status}")


def get_device_id(device: usb.core.Device) -> str:
    return f"{device.bus}:{device.address}"


def get_product_name(device: usb.core.Device) -> str:
    try:
        return device.product
    except (ValueError, usb.core.USBError):
        try:
            return usb.util.get_string(device, device.iProduct)
        except Exception:
            return "Unknown"


def get_target_usb_device(target_id: str | None = None) -> usb.core.Device | None:
    devices = list(usb.core.find(find_all=True, idVendor=USB_VENDOR_ID, idProduct=USB_PRODUCT_ID))

    if not devices:
        return None

    if len(devices) == 1 and target_id is None:
        return devices[0]

    if target_id:
        for dev in devices:
            if get_device_id(dev) == target_id:
                return dev

    devices.sort(key=lambda d: (d.bus, d.address))
    device_list_str = "\n".join(f"{get_device_id(dev)} - {get_product_name(dev)}" for dev in devices)

    raise ValueError(f"Multiple devices found. Please specify one using --device:\n{device_list_str}")


def parse_cli_arguments() -> dict[str, Any]:
    parser = argparse.ArgumentParser()

    parser.add_argument("--device", type=str)

    parser.add_argument("--audio_channel", choices=["stereo", "mono", "safety_track"])
    parser.add_argument("--gain", type=int, choices=[-12, -6, 0, 6, 12])
    parser.add_argument("--monitor_gain", type=int, choices=range(-12, 13))

    parser.add_argument("--clipping_control", action=argparse.BooleanOptionalAction)
    parser.add_argument("--auto_off_rx", action=argparse.BooleanOptionalAction)
    parser.add_argument("--receiver_on_off_with_camera", action=argparse.BooleanOptionalAction)

    parser.add_argument("--strong_noise_cancellation", action=argparse.BooleanOptionalAction)
    parser.add_argument("--power_button_for_noise_cancellation", action=argparse.BooleanOptionalAction)
    parser.add_argument("--low_cut", action=argparse.BooleanOptionalAction)
    parser.add_argument("--auto_off_tx", action=argparse.BooleanOptionalAction)
    parser.add_argument("--mic_led_off", action=argparse.BooleanOptionalAction)

    parser.add_argument(
        "--plug_free_external_speaker",
        action=argparse.BooleanOptionalAction,
        help="Restart required"
    )

    parser.add_argument("--debug", type=str)

    parsed_arguments = parser.parse_args()
    return {key: value for key, value in vars(parsed_arguments).items() if value is not None}


def main() -> None:
    user_configuration = parse_cli_arguments()
    target_id = user_configuration.pop("device", None)
    debug_file_path = user_configuration.pop("debug", None)

    try:
        target_usb_device = get_target_usb_device(target_id)

        if target_usb_device is None:
            print("Device not found.")
            return

        if debug_file_path:
            with FilePacketLogger(debug_file_path) as logger:
                manager = DjiMicManager(
                    target_usb_device,
                    on_packet_received=logger.log_packet,
                    on_status_update=display_system_status
                )
                manager.start_monitoring(user_configuration)
        else:
            manager = DjiMicManager(target_usb_device, on_status_update=display_system_status)
            manager.start_monitoring(user_configuration)
    except ValueError as error:
        print(error)


if __name__ == "__main__":
    main()
