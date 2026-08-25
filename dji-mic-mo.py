import argparse
import contextlib
import datetime
import json
import math
import queue
import signal
import sys
import threading

import usb.core
import usb.util


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


ADDR = {"rx": 0x00, "tx1": 0x01, "tx2": 0x02, "tx3": 0x04, "tx4": 0x08, "tx": 0xffff}

RULES = {
    "rx": {
        "deviceName":              (0x01, 45, vstr),
        "addressSuffix":           (0x01, 33, fstr(6)),
        "serialNumber":            (0x01, 13, fstr(14)),
        "firmwareVersion":         (0x01,  9, ver(True)),
        "batteryLevel":            (0x03, 10, bits(5, 0x07), "!DJI Mic Mini 2"),
        "charging":                (0x03, 10, bit(0x10), "!DJI Mic Mini 2"),
        "stereo":                  (0x03, 10, bit(0x04), 0x08, bl2),
        "quadraphonic":            (0x03, 10, bit(0x08), 0x08, bl4, "DJI Mic Mini 2S"),
        "safetyTrack":             (0x03, 37, bit(0x40), 0x21, bl1),
        "gainControl":             (0x03, 11, i8,        0x39, gain, "+DJI Mic Mini 2"),
        "monitoringGain":          (0x03, 16, i8,        0x26, gain1, "DJI Mic Mini 2"),
        "clippingControl":         (0x03, 37, bit(0x10), 0x1e, bl1),
        "autoOff":                 (0x03, 10, bit(0x01), 0x10, bl1, "!DJI Mic Mini 2"),
        "receiverOnOffWithCamera": (0x03,  9, bit(0x80), 0x20, bl1, "!DJI Mic Mini 2"),
        "plugFreeExternalSpeaker": (0x03, 37, bit(0x02), 0x23, bl1),
    },
    "tx": {
        "noiseCancellation":          (0x03,  7, bit(0x01), 0x38, bl1, "-DJI Mic Mini 2"),
        "noiseCancellationStrong":    (0x03,  6, bit(0x20), 0x37, bl1, "-DJI Mic Mini 2"),
        "noiseCancellationViaButton": (0x03,  6, bit(0x80), 0x0f, bl1, "!DJI Mic Mini 2"),
        "lowCut":                     (0x03,  9, bit(0x20), 0x03, bl1),
        "clippingControl":            (0x03,  8, bit(0x04), 0x24, bl1),
        "loudnessBalance":            (0x03, 11, bit(0x80), 0x2c, bl21),
        "autoOff":                    (0x03,  6, bit(0x10), 0x10, bl1),
        "micLedOff":                  (0x03,  6, bit(0x02), 0x0a, bl2),
    },
    "txi": {
        "deviceName":                (0x01, 42, vstr),
        "addressSuffix":             (0x01, 30, fstr(6)),
        "serialNumber":              (0x01, 10, fstr(14)),
        "firmwareVersion":           (0x01,  6, ver(True)),
        "batteryLevel":              (0x03,  7, bits(2, 0x07)),
        "charging":                  (0x03,  7, bit(0x02)),
        "inputLevel":                (0x05,  6, u8),
        "recordingTimeTotal":        (0x03, 14, f16, "DJI Mic Mini 2S"),
        "recordingTimeRemaining":    (0x03, 16, f16,       0x07, bl1, "DJI Mic Mini 2S"),
        "rec":                       (0x03,  9, bit(0x10), 0x02, bl1, "DJI Mic Mini 2S"),
        "transmitterGain":           (0x03, 13, i8,        0x39, gain1, "DJI Mic Mini 2S"),
        "voiceToneRich":             (0x03,  9, bit(0x40), 0x29, bl1, "!DJI Mic Mini"),
        "voiceToneBright":           (0x03,  9, bit(0x80), 0x29, bl2, "!DJI Mic Mini"),
        "fileOptionEditedFile":      (0x03, 31, bit(0x80), 0x3d, bl2, "DJI Mic Mini 2S"),
        "float32Recording":          (0x03,  9, bit(0x08), 0x0c, bl1, "DJI Mic Mini 2S"),
        "startupAutoRecording1":     (0x03,  8, bit(0x80), 0x2e, bl1, "DJI Mic Mini 2S"), # Mobile / Mini RX
        "startupAutoRecording2s":    (0x03, 31, bit(0x10), 0x3e, bl1, "DJI Mic Mini 2S"), # Mini 2S RX
        "autoRecordingWithReceiver": (0x03, 31, bit(0x20), 0x3e, bl2, "DJI Mic Mini 2S"), # Mini 2S RX
        "lowPowerAutoRecording":     (0x03, 11, bit(0x10), 0x2b, bl1, "DJI Mic Mini 2S"), # Mini 2S RX
        "loopRecording":             (0x03, 11, bit(0x08), 0x2a, bl1, "DJI Mic Mini 2S"),
        "recStop":                   (0x03, 11, bit(0x20), 0x0b, bl1, "DJI Mic Mini 2S"),
        "vibration":                 (0x03,  9, bit(0x01), 0x04, bl1, "DJI Mic Mini 2S"),
    },
}

usb_dev = None
usb_if = None
usb_ep = None
state = None
seq = 0
debug = False
device = None
cfg_queue = queue.Queue()
tx_queue = queue.Queue()
aborted = threading.Event()


def to_node(node):
    return "txi" if node in ("tx1", "tx2", "tx3", "tx4") else node


def valid(node, rule, write=False, typ=None, sz=None, base=None):
    if write:
        if len(rule) < 5: return False
    else:
        if rule[0] != typ or base + rule[1] >= sz: return False

    r_name = rule[-1]
    if not isinstance(r_name, str): return True
    if not write and (r_name.startswith("+") or r_name.startswith("-")): return True

    node_name = None
    if node in ("rx", "tx"):
        node_name = state["rx"]["deviceName"]
    elif node in ("tx1", "tx2", "tx3", "tx4"):
        node_name = state[node]["deviceName"]

    if node_name is None:
        return False

    if r_name.startswith("!") or r_name.startswith("-"):
        return node_name != r_name[1:]
    return node_name == (r_name[1:] if r_name.startswith("+") else r_name)


def scan(data):
    sz = len(data)
    if sz < 4: return {"typ": None, "rx": None, "tx1": None, "tx2": None, "tx3": None, "tx4": None}

    blk = {"typ": data[3], "rx": None, "tx1": None, "tx2": None, "tx3": None, "tx4": None}

    if blk["typ"] == 0x01 and sz >= 45:
        blk["rx"] = 0
        i = 45 + data[44]
        while i + 42 <= sz:
            if data[i] == 0x01 and data[i + 1] in (0x01, 0x02, 0x04, 0x08):
                blk[f"tx{int(math.log2(data[i + 1])) + 1}"] = i
            i += 42 + data[i + 41]
        return blk

    if blk["typ"] == 0x03 and sz >= 41:
        blk["rx"] = 0
        for i in range(41, sz - 31, 32):
            if data[i] == 0x02 and data[i + 1] in (0x01, 0x02, 0x04, 0x08):
                blk[f"tx{int(math.log2(data[i + 1])) + 1}"] = i
        return blk

    if blk["typ"] == 0x05 and sz >= 10:
        for i in range(3, sz - 6, 7):
            if data[i] == 0x05 and data[i + 1] in (0x01, 0x02, 0x04, 0x08):
                blk[f"tx{int(math.log2(data[i + 1])) + 1}"] = i
        return blk

    return blk


def read(node, data, typ, base, obj):
    for key, rule in RULES[to_node(node)].items():
        if not valid(node, rule, False, typ, len(data), base): continue
        obj[key] = rule[2](data, base + rule[1])


def init(node):
    return dict.fromkeys(RULES[node])


def parse(pkt):
    if pkt[9] != 0x5b or pkt[10] != 0x03: return

    data = pkt[11:-2]
    blk = scan(data)

    if blk["rx"] is not None:
        read("rx", data, blk["typ"], blk["rx"], state["rx"])

    for n in (1, 2, 3, 4):
        base = blk[f"tx{n}"]
        if base is None:
            if blk["typ"] in (0x01, 0x03):
                state[f"tx{n}"] = None
            continue

        if state[f"tx{n}"] is None:
            state[f"tx{n}"] = init("txi")
        read(f"tx{n}", data, blk["typ"], base, state[f"tx{n}"])

    if blk["tx1"] is None and blk["tx2"] is None and blk["tx3"] is None and blk["tx4"] is None:
        if blk["typ"] in (0x01, 0x03):
            state["tx"] = None
        return

    if state["tx"] is None:
        state["tx"] = init("tx")

    base = next(b for b in (blk["tx1"], blk["tx2"], blk["tx3"], blk["tx4"]) if b is not None)
    read("tx", data, blk["typ"], base, state["tx"])


def send(node_addr, cmd, val):
    global seq
    if not usb_dev: return

    pkt = bytearray(22)
    pkt[0] = 0x55
    pkt[1:3] = (0x16, 0x04)
    pkt[3] = crc8(pkt[:3])
    pkt[4:6] = (0x02, 0x5a)
    pkt[6:8] = seq.to_bytes(2, "little")
    pkt[8:20] = (
        0x40, 0x5b, 0x01, 0x02, node_addr & 0xff, (node_addr >> 8) & 0xff, 0x00, 0x00,
        cmd, 0x00, 0x01, val,
    )
    pkt[20:] = crc16(pkt[:20]).to_bytes(2, "little")

    seq = (seq + 1) & 0xffff

    tx_queue.put(pkt)


def send_time():
    global seq
    if not usb_dev: return

    d = datetime.datetime.now()

    pkt = bytearray(29)
    pkt[0] = 0x55
    pkt[1:3] = (0x1d, 0x04)
    pkt[3] = crc8(pkt[:3])
    pkt[4:6] = (0x02, 0x5a)
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

        rule = RULES[to_node(self.node)].get(key)
        if not rule: return
        if not valid(self.node, rule, True): return

        enc = rule[4](val)
        if enc is None: return

        send(ADDR[self.node], rule[3], enc)

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
    if not state or not state["rx"]["deviceName"]: return

    if not cfg_queue.empty():
        send_time()

    while True:
        try:
            cfg = cfg_queue.get_nowait()
        except queue.Empty:
            break

        if not isinstance(cfg, dict): continue

        spk = None

        if isinstance(rx := cfg.get("rx"), dict):
            spk = rx.pop("plugFreeExternalSpeaker", None)
            ctrl.rx |= rx

        if ctrl.tx and isinstance(tx := cfg.get("tx"), dict):
            ctrl.tx |= tx

        if ctrl.tx1 and isinstance(tx1 := cfg.get("tx1"), dict):
            ctrl.tx1 |= tx1

        if ctrl.tx2 and isinstance(tx2 := cfg.get("tx2"), dict):
            ctrl.tx2 |= tx2

        if ctrl.tx3 and isinstance(tx3 := cfg.get("tx3"), dict):
            ctrl.tx3 |= tx3

        if ctrl.tx4 and isinstance(tx4 := cfg.get("tx4"), dict):
            ctrl.tx4 |= tx4

        if spk is not None:
            ctrl.rx.plugFreeExternalSpeaker = spk


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


def match(d):
    if d.idVendor != 0x2ca3 or d.idProduct not in (0x4011, 0x4015, 0x4115):
        return False
    if device and device != f"{d.bus}:{d.address}":
        return False
    return True


def stream(dev):
    buf = b""
    while not aborted.is_set():
        try:
            chunk = dev.read(0x80 | usb_ep, 1024, timeout=10 if not tx_queue.empty() else 100)
            if chunk: buf += bytes(chunk)
        except usb.core.USBTimeoutError:
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


def main():
    global usb_dev, usb_if, usb_ep, state, seq

    devs = list(usb.core.find(find_all=True, custom_match=match))

    if not devs:
        raise RuntimeError(f"Device {device} not found" if device else "Device not found")

    if len(devs) > 1:
        dev_list = "\n".join(
            f"  {d.bus}:{d.address}"
            for d in sorted(devs, key=lambda d: (d.bus, d.address))
        )
        raise RuntimeError(f"Multiple devices found. Specify one using --device:\n{dev_list}")

    usb_dev = devs[0]
    usb_if = 6 if usb_dev.idProduct == 0x4011 else 4
    usb_ep = 6 if usb_dev.idProduct == 0x4011 else 4

    ucfg = None
    with contextlib.suppress(usb.core.USBError):
        ucfg = usb_dev.get_active_configuration()

    if ucfg is None:
        with contextlib.suppress(usb.core.USBError):
            usb_dev.set_configuration()

    detached = False
    try:
        with contextlib.suppress(NotImplementedError, usb.core.USBError):
            usb_dev.detach_kernel_driver(usb_if)
            detached = True
        usb.util.claim_interface(usb_dev, usb_if)

        if usb_dev.idProduct != 0x4011:
            usb_dev.set_interface_altsetting(interface=usb_if, alternate_setting=1)

        state = {"rx": init("rx"), "tx": None, "tx1": None, "tx2": None, "tx3": None, "tx4": None}
        seq = 0

        last = ""

        for pkt in stream(usb_dev):
            apply()

            with contextlib.suppress(queue.Empty):
                tx_pkt = tx_queue.get_nowait()
                with contextlib.suppress(usb.core.USBError):
                    usb_dev.write(usb_ep, tx_pkt, timeout=1000)
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

        raise KeyboardInterrupt()

    finally:
        state = None
        seq = 0
        cfg_queue.queue.clear()
        tx_queue.queue.clear()
        aborted.clear()

        if usb_dev:
            with contextlib.suppress(usb.core.USBError):
                usb.util.release_interface(usb_dev, usb_if)
            if detached:
                with contextlib.suppress(usb.core.USBError):
                    usb_dev.attach_kernel_driver(usb_if)
            usb.util.dispose_resources(usb_dev)
            usb_dev = None


def abort(sig, _frame):
    aborted.set()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--device")
    args = parser.parse_args()
    debug = args.debug
    device = args.device

    signal.signal(signal.SIGTERM, abort)
    signal.signal(signal.SIGINT, abort)

    threading.Thread(target=poll, daemon=True).start()

    try:
        main()
    except KeyboardInterrupt:
        print(json.dumps({"e": "Terminated"}, ensure_ascii=False, indent=2))
    except BrokenPipeError:
        sys.exit()
    except Exception as e:
        print(json.dumps({"e": f"{type(e).__name__}: {str(e)}"}, ensure_ascii=False, indent=2))
        sys.exit(1)
