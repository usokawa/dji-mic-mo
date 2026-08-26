import argparse
import asyncio
import contextlib
import datetime
import json
import queue
import signal
import sys
import threading

from bleak import BleakScanner, BleakClient, BleakError

sys.stdin.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IS_TTY = sys.stdout.isatty()


def ver(rev):
    return lambda buf, off: ".".join(f"{b:02d}" for b in (reversed(buf[off : off + 4]) if rev else buf[off : off + 4]))


def fstr(sz):
    return lambda buf, off: buf[off : off + sz].decode(errors="replace")


def vstr(buf, off):
    return buf[off : off + buf[off - 1]].decode(errors="replace")


def f16(buf, off):
    return int.from_bytes(buf[off : off + 2], "little") / 10


def i8(buf, off):
    return int.from_bytes(buf[off : off + 1], "little", signed=True)


def u8(buf, off):
    return buf[off]


def bits(shift, mask):
    return lambda buf, off: (buf[off] >> shift) & mask


def bit(mask):
    return lambda buf, off: bool(buf[off] & mask)


def bl1(val):
    return 1 if val is True else 0 if val is False else None


def bl2(val):
    return 2 if val is True else 0 if val is False else None


def bl21(val):
    return 2 if val is True else 1 if val is False else None


def bl4(val):
    return 4 if val is True else 0 if val is False else None


def gain(val):
    return int(val) & 0xff if type(val) in (int, float) and val in (-12, -6, 0, 6, 12) else None


def gain1(val):
    return int(val) & 0xff if type(val) in (int, float) and -12 <= val <= 12 and int(val) == val else None


def _init_crc():
    t8 = [0] * 256
    t16 = [0] * 256
    for i in range(256):
        c = i
        k = i
        for _ in range(8):
            c = (c >> 1) ^ (-(c & 1) & 0x8c)
            k = (k >> 1) ^ (-(k & 1) & 0x8408)
        t8[i] = c
        t16[i] = k
    return tuple(t8), tuple(t16)


T8, T16 = _init_crc()


def crc8(buf):
    c = 0x77
    for b in buf:
        c = T8[c ^ b]
    return c


def crc16(buf):
    c = 0x3692
    for b in buf:
        c = (c >> 8) ^ T16[(c ^ b) & 0xff]
    return c


def dump(pkt):
    hdr = int.from_bytes(pkt[1:3], "little")
    pkt_ver = (hdr >> 10) & 0x3f
    pkt_len = hdr & 0x3ff
    pkt_seq = int.from_bytes(pkt[6:8], "little")
    data = pkt[11:-2]

    lines = [
        f"Ver: {pkt_ver} Len: {pkt_len}({len(data)}) "
        f"Src: {pkt[4]:02x} Dst: {pkt[5]:02x} "
        f"Seq: {pkt_seq:04x} Type: {pkt[8]:02x} "
        f"Set: {pkt[9]:02x} ID: {pkt[10]:02x}",
    ]

    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        left = chunk[:8].hex(" ")
        right = chunk[8:].hex(" ")
        hex_str = f"{left}  {right}" if right else left
        ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{i:04x}  {hex_str:<48}  |{ascii_str}|")

    return "\n".join(lines)


RULES = {
    "tx": {
        "serialNumber":               (0x01, 12, vstr),
        "firmwareVersion":            (0x01,  7, ver(False)),
        "batteryLevel":               (0x01,  4, bits(2, 0x07)),
        "charging":                   (0x01,  4, bit(0x02)),
        "noiseCancellationViaButton": (0x01,  3, bit(0x80), 0x0f, bl1),
        "autoOff":                    (0x01,  3, bit(0x10), 0x10, bl1),
        "micLedOff":                  (0x01,  6, bit(0x80), 0x0a, bl2),
    }
}


RULES_MINI_2S = {
    "tx": {
        "serialNumber":               (0x01, 13, fstr(14)),
        "firmwareVersion":            (0x01,  9, ver(True)),
        "batteryLevel":               (0x02, 10, bits(2, 0x07)),
        "charging":                   (0x02, 10, bit(0x02)),
        "recordingTimeTotal":         (0x02, 17, f16),
        "recordingTimeRemaining":     (0x02, 19, f16,       0x07, bl1),
        "rec":                        (0x02, 12, bit(0x10), 0x02, bl1),
        "transmitterGain":            (0x02, 16, i8,        0x39, gain1),
        "voiceToneRich":              (0x02, 12, bit(0x40), 0x29, bl1),
        "voiceToneBright":            (0x02, 12, bit(0x80), 0x29, bl2),
        "fileOptionEditedFile":       (0x02, 34, bit(0x80), 0x3d, bl2),
        "float32Recording":           (0x02, 12, bit(0x08), 0x0c, bl1),
        "startupAutoRecording2s":     (0x02, 34, bit(0x10), 0x3e, bl1),
        "autoRecordingWithReceiver":  (0x02, 34, bit(0x20), 0x3e, bl2),
        "lowPowerAutoRecording":      (0x02, 14, bit(0x10), 0x2b, bl1),
        "loopRecording":              (0x02, 14, bit(0x08), 0x2a, bl1),
        "recStop":                    (0x02, 14, bit(0x20), 0x0b, bl1),
        "vibration":                  (0x02, 12, bit(0x01), 0x04, bl1),
        "noiseCancellation":          (0x02, 10, bit(0x01), 0x0e, bl1),
        "noiseCancellationStrong":    (0x02,  9, bit(0x20), 0x1d, bl1),
        "noiseCancellationViaButton": (0x02,  9, bit(0x80), 0x0f, bl1),
        "lowCut":                     (0x02, 12, bit(0x20), 0x03, bl1),
        "clippingControl":            (0x02, 11, bit(0x04), 0x24, bl1),
        "loudnessBalance":            (0x02, 14, bit(0x80), 0x2c, bl21),
        "autoOff":                    (0x02,  9, bit(0x10), 0x10, bl1),
        "micLedOff":                  (0x02,  9, bit(0x02), 0x0a, bl2),
    }
}


active_rules = RULES

state = None
seq = 0
debug = False
device_mac = None
is_mini_2s = False
cfg_queue = queue.Queue()
tx_queue = queue.Queue()
rx_queue = asyncio.Queue()
aborted = threading.Event()
disconnected = threading.Event()


def valid(rule, write=False, typ=None, sz=None, base=None):
    if write:
        if len(rule) < 5: return False
    else:
        if rule[0] != typ or base + rule[1] >= sz: return False

    return True


def scan(data):
    if len(data) < 4: return {"typ": None, "base": None}

    typ = data[3] if is_mini_2s else data[0]

    return {"typ": typ, "base": 0}


def read(node, data, typ, base, obj):
    for key, rule in active_rules[node].items():
        if not valid(rule, False, typ, len(data), base): continue
        obj[key] = rule[2](data, base + rule[1])


def init(node):
    return dict.fromkeys(active_rules[node])


def parse(pkt):
    if pkt[9] != 0x5b or pkt[10] != 0x03: return

    data = pkt[11:-2]
    blk = scan(data)

    if blk["typ"] is not None and blk["base"] is not None:
        read("tx", data, blk["typ"], blk["base"], state["tx"])


def send_old(cmd, val):
    global seq

    pkt = bytearray(19)
    pkt[0] = 0x55
    pkt[1:3] = (0x13, 0x04)
    pkt[3] = crc8(pkt[:3])
    pkt[4:6] = (0x02, 0x3a)
    pkt[6:8] = seq.to_bytes(2, "little")
    pkt[8:17] = (
        0x40, 0x5b, 0x01, 0x00, 0x00,
        cmd, 0x00, 0x01, val,
    )
    pkt[17:] = crc16(pkt[:17]).to_bytes(2, "little")

    seq = (seq + 1) & 0xffff

    tx_queue.put(pkt)


def send(cmd, val):
    global seq

    pkt = bytearray(22)
    pkt[0] = 0x55
    pkt[1:3] = (0x16, 0x04)
    pkt[3] = crc8(pkt[:3])
    pkt[4:6] = (0x02, 0x3a)
    pkt[6:8] = seq.to_bytes(2, "little")
    pkt[8:20] = (
        0x40, 0x5b, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00,
        cmd, 0x00, 0x01, val,
    )
    pkt[20:] = crc16(pkt[:20]).to_bytes(2, "little")

    seq = (seq + 1) & 0xffff

    tx_queue.put(pkt)


def send_time():
    global seq

    d = datetime.datetime.now()

    pkt = bytearray(29)
    pkt[0] = 0x55
    pkt[1:3] = (0x1d, 0x04)
    pkt[3] = crc8(pkt[:3])
    pkt[4:6] = (0x02, 0x3a)
    pkt[6:8] = seq.to_bytes(2, "little")
    pkt[8:27] = (
        0x40, 0x5b, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x33, 0x00, 0x08, 0x09,
        d.year % 100, d.month, d.day, d.hour, d.minute, d.second, 0x00
    )
    pkt[27:] = crc16(pkt[:27]).to_bytes(2, "little")

    seq = (seq + 1) & 0xffff

    tx_queue.put(pkt)


class Node:
    def __init__(self, node, obj):
        self.__dict__["node"] = node
        self.__dict__["obj"] = obj

    def __getattr__(self, key):
        try:
            return self.obj[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key, val):
        if key not in self.obj or (self.obj[key] == val and type(self.obj[key]) is type(val)): return

        rule = active_rules[self.node].get(key)
        if not rule: return
        if not valid(rule, True): return

        enc = rule[4](val)
        if enc is None: return

        if is_mini_2s:
            send(rule[3], enc)
        else:
            send_old(rule[3], enc)

    def __ior__(self, other):
        for key, val in other.items():
            setattr(self, key, val)
        return self


class Ctrl:
    def __getattr__(self, node):
        try:
            val = state[node]
            if val is None: return None
            return Node(node, val)
        except KeyError:
            raise AttributeError(node) from None

    def __setattr__(self, key, val):
        pass


ctrl = Ctrl()


def apply():
    if not state or not state["tx"]["deviceName"]: return

    if is_mini_2s and not cfg_queue.empty():
        send_time()

    while True:
        try:
            cfg = cfg_queue.get_nowait()
        except queue.Empty:
            break

        if not isinstance(cfg, dict): continue

        if ctrl.tx and isinstance(tx := cfg.get("tx"), dict):
            ctrl.tx |= tx


def poll():
    buf = ""
    jdec = json.JSONDecoder()
    for line in sys.stdin:
        buf += line
        while buf := buf.lstrip():
            try:
                obj, skip = jdec.raw_decode(buf)
                buf = buf[skip:]
                if not isinstance(obj, dict): continue
                cfg_queue.put(obj)
            except json.JSONDecodeError:
                break


def rx_handler(sender, data):
    rx_queue.put_nowait(data)


async def stream():
    buf = b""
    while True:
        if disconnected.is_set():
            raise RuntimeError("Device disconnected")
        if aborted.is_set():
            break
        try:
            chunk = await asyncio.wait_for(rx_queue.get(), timeout=1.0 if tx_queue.empty() else 0.1)
            if chunk: buf += bytes(chunk)
        except asyncio.TimeoutError:
            yield None
            continue

        off = 0
        while off < len(buf):
            idx = buf.find(0x55, off)
            if idx < 0:
                off = len(buf)
                break
            off = idx

            if len(buf) - off < 4: break
            if crc8(buf[off : off + 3]) != buf[off + 3]:
                off += 1
                continue

            sz = int.from_bytes(buf[off + 1 : off + 3], "little") & 0x3ff
            if sz < 13:
                off += 1
                continue
            if sz > len(buf) - off: break

            pkt = buf[off : off + sz]
            if crc16(pkt[:-2]) != int.from_bytes(pkt[-2:], "little"):
                off += 1
                continue
            off += sz

            yield pkt

        buf = buf[off:]


def prune(d):
    return {key: prune(val) for key, val in d.items() if val is not None} if isinstance(d, dict) else d


async def main():
    global state, seq, active_rules, is_mini_2s

    if device_mac:
        device = await BleakScanner.find_device_by_address(device_mac, timeout=10.0)
        if not device:
            raise RuntimeError(f"Device {device_mac} not found")
    else:
        devices = await BleakScanner.discover(timeout=5.0)
        dji_devs = [d for d in devices if d.name and "DJI Mic" in d.name]
        if not dji_devs:
            raise RuntimeError("Device not found")
        if len(dji_devs) > 1:
            dev_list = "\n".join(f"  {d.address} - {d.name}" for d in sorted(dji_devs, key=lambda d: d.address))
            raise RuntimeError(f"Multiple devices found. Specify one using --device:\n{dev_list}")
        device = dji_devs[0]

    parts = device.name.split("-")
    dev_name = "-".join(parts[:-1])
    suffix = parts[-1] if len(parts) >= 2 else ""
    is_mini_2s = "Mini 2S" in dev_name
    active_rules = RULES_MINI_2S if is_mini_2s else RULES

    def handle_disconnect(_client):
        disconnected.set()
        aborted.set()

    try:
        async with BleakClient(device, disconnected_callback=handle_disconnect) as client:
            await client.start_notify("0000fff4-0000-1000-8000-00805f9b34fb", rx_handler)

            state = {"tx": {**{"deviceName": dev_name, "addressSuffix": suffix}, **init("tx")}}
            seq = 0

            last = ""

            async for pkt in stream():
                apply()

                with contextlib.suppress(queue.Empty):
                    tx_pkt = tx_queue.get_nowait()
                    with contextlib.suppress(BleakError):
                        await client.write_gatt_char("0000fff4-0000-1000-8000-00805f9b34fb", tx_pkt)
                        if debug:
                            print(f"{dump(tx_pkt)}\n", file=sys.stderr, flush=True)

                if pkt is None: continue

                if debug:
                    print(f"{dump(pkt)}\n", file=sys.stderr, flush=True)

                parse(pkt)

                pruned = prune(state)
                curr = json.dumps(pruned, ensure_ascii=False, indent=2)
                if curr == last: continue
                if IS_TTY:
                    print(f"\033[H\033[J{curr}", end="", flush=True)
                else:
                    print(curr, flush=True)
                last = curr
    finally:
        state = None
        seq = 0
        cfg_queue.queue.clear()
        tx_queue.queue.clear()
        while not rx_queue.empty():
            rx_queue.get_nowait()
        aborted.clear()
        disconnected.clear()


def abort(sig, _frame):
    aborted.set()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--device")
    args = parser.parse_args()
    debug = args.debug
    device_mac = args.device

    signal.signal(signal.SIGTERM, abort)
    signal.signal(signal.SIGINT, abort)

    threading.Thread(target=poll, daemon=True).start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(json.dumps({"e": "Terminated"}, ensure_ascii=False, indent=2))
    except BrokenPipeError:
        sys.exit()
    except Exception as e:
        print(json.dumps({"e": f"{type(e).__name__}: {str(e)}"}, ensure_ascii=False, indent=2))
        sys.exit(1)
