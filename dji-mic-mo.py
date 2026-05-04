import argparse
import contextlib
import json
import queue
import signal
import sys
import threading

import usb.core
import usb.util


if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IS_TTY = sys.stdout.isatty()

usb_dev = None
state = None
seq = 0
debug = False
device = None


def ver(buf, off):
    return ".".join(f"{b:02d}" for b in reversed(buf[off : off + 4]))


def fstr(sz):
    def _fstr(buf, off):
        return buf[off : off + sz].decode("utf-8", "replace")
    return _fstr


def vstr(buf, off):
    return buf[off : off + buf[off - 1]].decode("utf-8", "replace")


def i8(buf, off):
    return int.from_bytes(buf[off : off + 1], "little", signed=True)


def u8(buf, off):
    return buf[off]


def bits(shift, mask):
    def _bits(buf, off):
        return (buf[off] >> shift) & mask
    return _bits


def bit(mask):
    def _bit(buf, off):
        return bool(buf[off] & mask)
    return _bit


def bl1(val):
    return (1 if val else 0) if isinstance(val, bool) else None


def bl2(val):
    return (2 if val else 0) if isinstance(val, bool) else None


def gain(val):
    return int(val) & 0xff if isinstance(val, (int, float)) and not isinstance(val, bool) and val in (-12, -6, 0, 6, 12) else None


def mgain(val):
    return int(val) & 0xff if isinstance(val, (int, float)) and not isinstance(val, bool) and val == int(val) and -12 <= val <= 12 else None


ADDR = {"rx": 0, "tx1": 1 << 0, "tx2": 1 << 1, "tx": ~0}

RULES = {
    "rx": {
        "firmwareVersion":         (0x01,  9, ver),
        "serialNumber":            (0x01, 13, fstr(14)),
        "addressSuffix":           (0x01, 33, fstr(6)),
        "deviceName":              (0x01, 45, vstr),
        "batteryLevel":            (0x03, 10, bits(5, 0x07), "DJI Mic Mini"),
        "charging":                (0x03, 10, bit(0x10), "DJI Mic Mini"),
        "stereo":                  (0x03, 10, bit(0x04), 0x08, bl2),
        "safetyTrack":             (0x03, 37, bit(0x40), 0x21, bl1),
        "gainControl":             (0x03, 11, i8,        0x39, gain, "+DJI Mic Mini 2"),
        "monitoringGain":          (0x03, 16, i8,        0x26, mgain, "DJI Mic Mini 2"),
        "clippingControl":         (0x03, 37, bit(0x10), 0x1e, bl1),
        "autoOff":                 (0x03, 10, bit(0x01), 0x10, bl1, "DJI Mic Mini"),
        "receiverOnOffWithCamera": (0x03,  9, bit(0x80), 0x20, bl1, "DJI Mic Mini"),
        "plugFreeExternalSpeaker": (0x03, 37, bit(0x02), 0x23, bl1),
    },
    "tx": {
        "noiseCancellation":          (0x03,  7, bit(0x01), 0x38, bl1, "+DJI Mic Mini"),
        "noiseCancellationStrong":    (0x03,  6, bit(0x20), 0x37, bl1, "+DJI Mic Mini"),
        "noiseCancellationViaButton": (0x03,  6, bit(0x80), 0x0f, bl1, "DJI Mic Mini"),
        "lowCut":                     (0x03,  9, bit(0x20), 0x03, bl1),
        "autoOff":                    (0x03,  6, bit(0x10), 0x10, bl1),
        "micLedOff":                  (0x03,  6, bit(0x02), 0x0a, bl2),
    },
    "txi": {
        "firmwareVersion":         (0x01,  6, ver),
        "serialNumber":            (0x01, 10, fstr(14)),
        "addressSuffix":           (0x01, 30, fstr(6)),
        "deviceName":              (0x01, 42, vstr),
        "voiceToneRich":           (0x03,  9, bit(0x40), 0x29, bl1, "DJI Mic Mini 2"),
        "voiceToneBright":         (0x03,  9, bit(0x80), 0x29, bl2, "DJI Mic Mini 2"),
        "batteryLevel":            (0x03,  7, bits(2, 0x07)),
        "charging":                (0x03,  7, bit(0x02)),
        "inputLevel":              (0x05,  6, u8),
    },
}


def _init_crc():
    t8 = [0] * 256
    t16 = [0] * 256
    for i in range(256):
        c = i
        k = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8c if c & 1 else c >> 1
            k = (k >> 1) ^ 0x8408 if k & 1 else k >> 1
        t8[i] = c
        t16[i] = k
    return tuple(t8), tuple(t16)


T8, T16 = _init_crc()
del _init_crc


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
    data = pkt[11:-2]
    pkt_seq = int.from_bytes(pkt[6:8], "little")

    lines = [
        f"Ver: {pkt_ver} Len: {pkt_len}({len(data)}) "
        f"Src: {pkt[4]:02x} Dst: {pkt[5]:02x} "
        f"Seq: {pkt_seq:04x} Type: {pkt[8]:02x} "
        f"Set: {pkt[9]:02x} ID: {pkt[10]:02x}",
    ]

    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hex_str = "  ".join(filter(None, (chunk[:8].hex(" "), chunk[8:].hex(" "))))
        ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        lines.append(f"{i:04x}  {hex_str:<48}  |{ascii_str}|")

    return "\n".join(lines)


def get_node(node):
    return "txi" if node != "tx" and node.startswith("tx") else node


def check(node, rule, write=False, typ=None, sz=None, base=None):
    if write:
        if len(rule) < 5: return False
    else:
        if rule[0] != typ or base + rule[1] >= sz: return False

    r_name = rule[-1]
    if not isinstance(r_name, str): return True
    if not write and r_name.startswith("+"): return True

    node_name = None
    if node in ("rx", "tx"): node_name = state["rx"]["deviceName"]
    elif node in ("tx1", "tx2"): node_name = state[node]["deviceName"]

    return node_name == (r_name[1:] if r_name.startswith("+") else r_name)


def send(node_addr, cmd, val):
    global seq
    if not usb_dev: return

    pkt = bytearray(22)
    pkt[0] = 0x55
    pkt[1:3] = [0x16, 0x04]
    pkt[3] = crc8(pkt[:3])
    pkt[4:6] = [0x02, 0x5a]
    pkt[6:8] = seq.to_bytes(2, "little")
    seq = (seq + 1) & 0xffff
    addr_lo = node_addr & 0xff
    addr_hi = (node_addr >> 8) & 0xff
    pkt[8:20] = [
        0x40, 0x5b, 0x01, 0x02, addr_lo, addr_hi, 0x00, 0x00,
        cmd, 0x00, 0x01, val,
    ]
    pkt[20:] = crc16(pkt[:20]).to_bytes(2, "little")

    with contextlib.suppress(usb.core.USBError):
        usb_dev.write(0x06, pkt, timeout=1000)
        if debug:
            print(f"{dump(pkt)}\n", file=sys.stderr, flush=True)


class Node:
    def __init__(self, node, obj):
        self.__dict__["node"] = node
        self.__dict__["obj"] = obj

    def __getattr__(self, key):
        try:
            return self.obj[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, val):
        if key not in self.obj or self.obj[key] == val: return
        rule = RULES[get_node(self.node)].get(key)
        if not rule: return
        if not check(self.node, rule, True): return
        enc = rule[4](val)
        if enc is None: return

        send(ADDR[self.node], rule[3], enc)

    def update(self, cfg):
        for key, val in cfg.items():
            setattr(self, key, val)


class Ctrl:
    def __getattr__(self, node):
        try:
            val = state[node]
            if val is None: return None
            return Node(node, val)
        except KeyError:
            raise AttributeError(node)


def scan(data):
    sz = len(data)
    if sz < 4: return {"typ": None, "rx": None, "tx1": None, "tx2": None}

    blk = {"typ": data[3], "rx": None, "tx1": None, "tx2": None}

    if blk["typ"] == 0x01 and sz >= 45:
        blk["rx"] = 0
        i = 45 + data[44]
        while i + 42 <= sz:
            if data[i] == 0x01 and data[i + 1] in (1, 2):
                blk[f"tx{data[i + 1]}"] = i
            i += 42 + data[i + 41]
        return blk

    if blk["typ"] == 0x03 and sz >= 41:
        blk["rx"] = 0
        for i in range(41, sz - 31, 32):
            if data[i] == 0x02 and data[i + 1] in (1, 2):
                blk[f"tx{data[i + 1]}"] = i
        return blk

    if blk["typ"] == 0x05 and sz >= 10:
        for i in range(3, sz - 6, 7):
            if data[i] == 0x05 and data[i + 1] in (1, 2):
                blk[f"tx{data[i + 1]}"] = i
        return blk

    return blk


def read(node, data, typ, base, obj):
    for key, rule in RULES[get_node(node)].items():
        if not check(node, rule, False, typ, len(data), base): continue
        obj[key] = rule[2](data, base + rule[1])


def make(node):
    return dict.fromkeys(RULES[node])


def parse(pkt):
    if pkt[9] != 0x5b or pkt[10] != 0x03: return

    data = pkt[11:-2]
    blk = scan(data)

    if blk["rx"] is not None:
        read("rx", data, blk["typ"], blk["rx"], state["rx"])

    for n in (1, 2):
        base = blk[f"tx{n}"]
        if base is None:
            if blk["typ"] in (0x01, 0x03):
                state[f"tx{n}"] = None
            continue
        if state[f"tx{n}"] is None:
            state[f"tx{n}"] = make("txi")
        read(f"tx{n}", data, blk["typ"], base, state[f"tx{n}"])

    if blk["tx1"] is None and blk["tx2"] is None:
        if blk["typ"] in (0x01, 0x03):
            state["tx"] = make("tx")
        return
    read("tx", data, blk["typ"], blk["tx1"] or blk["tx2"], state["tx"])


def prune(d):
    return {key: prune(val) for key, val in d.items() if val is not None} if isinstance(d, dict) else d


cfg_queue = queue.Queue()
ctrl = Ctrl()


def apply():
    if not state or not state["rx"]["deviceName"]: return

    while True:
        try:
            cfg = cfg_queue.get_nowait()
        except queue.Empty:
            break

        if not isinstance(cfg, dict): continue

        spk = None

        if ctrl.rx and isinstance(rx := cfg.get("rx"), dict):
            spk = rx.pop("plugFreeExternalSpeaker", None)
            ctrl.rx.update(rx)

        if ctrl.tx and isinstance(tx := cfg.get("tx"), dict):
            ctrl.tx.update(tx)

        if ctrl.tx1 and isinstance(tx1 := cfg.get("tx1"), dict):
            ctrl.tx1.update(tx1)

        if ctrl.tx2 and isinstance(tx2 := cfg.get("tx2"), dict):
            ctrl.tx2.update(tx2)

        if spk is not None and ctrl.rx:
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
    if d.idVendor != 0x2ca3 or d.idProduct != 0x4011:
        return False
    if device and device not in (f"{d.bus:03d}:{d.address:03d}", f"{d.bus}:{d.address}"):
        return False
    return True


aborted = threading.Event()


def main():
    global usb_dev, state, seq

    devs = list(usb.core.find(find_all=True, custom_match=match))

    if not devs:
        raise RuntimeError(f"Device {device} not found" if device else "Device not found")

    if len(devs) > 1:
        dev_list = "\n".join(
            f"  {d.bus:03d}:{d.address:03d}"
            for d in sorted(devs, key=lambda d: (d.bus, d.address))
        )
        raise RuntimeError(f"Multiple devices found. Specify one using --device:\n{dev_list}")

    usb_dev = devs[0]

    try:
        ucfg = usb_dev.get_active_configuration()
    except usb.core.USBError:
        ucfg = None

    if ucfg is None:
        with contextlib.suppress(usb.core.USBError):
            usb_dev.set_configuration()

    detached = False
    try:
        with contextlib.suppress(NotImplementedError, usb.core.USBError):
            if usb_dev.is_kernel_driver_active(6):
                usb_dev.detach_kernel_driver(6)
                detached = True
        usb.util.claim_interface(usb_dev, 6)

        state = {"rx": make("rx"), "tx": make("tx"), "tx1": None, "tx2": None}
        seq = 0

        while not cfg_queue.empty():
            try:
                cfg_queue.get_nowait()
            except queue.Empty:
                break

        buf = bytearray()
        last = ""

        while not aborted.is_set():
            apply()
            try:
                chunk = usb_dev.read(0x86, 1024, timeout=100)
                if not chunk: continue
                buf.extend(chunk)
            except usb.core.USBTimeoutError:
                continue

            while buf:
                idx = buf.find(0x55)
                if idx < 0:
                    buf.clear()
                    break
                if idx > 0:
                    del buf[:idx]
                if len(buf) < 4: break
                if crc8(buf[:3]) != buf[3]:
                    del buf[:1]
                    continue

                sz = int.from_bytes(buf[1:3], "little") & 0x3ff
                if sz < 13:
                    del buf[:1]
                    continue
                if sz > len(buf): break

                pkt = buf[:sz]
                if crc16(pkt[:-2]) != int.from_bytes(pkt[-2:], "little"):
                    del buf[:1]
                    continue
                del buf[:sz]

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
        aborted.clear()

        if usb_dev:
            with contextlib.suppress(usb.core.USBError):
                usb.util.release_interface(usb_dev, 6)
            if detached:
                with contextlib.suppress(usb.core.USBError):
                    usb_dev.attach_kernel_driver(6)
            usb.util.dispose_resources(usb_dev)

        while not cfg_queue.empty():
            try:
                cfg_queue.get_nowait()
            except queue.Empty:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--device")
    args = parser.parse_args()
    debug = args.debug
    device = args.device

    def abort(sig, _frame):
        aborted.set()

    signal.signal(signal.SIGTERM, abort)
    signal.signal(signal.SIGINT, abort)

    threading.Thread(target=poll, daemon=True).start()

    try:
        main()
    except KeyboardInterrupt:
        print(json.dumps({"e": "Terminated"}, ensure_ascii=False, indent=2), flush=True)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as e:
        print(json.dumps({"e": f"{type(e).__name__}: {str(e)}"}, ensure_ascii=False, indent=2), flush=True)
        sys.exit(1)
