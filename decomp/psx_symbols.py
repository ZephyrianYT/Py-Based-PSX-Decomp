"""PS1 address-space knowledge handed to Ghidra (see ref/hardware/overview.md, gte.md).

Ghidra's stock MIPS support knows the CPU but not the console. These tables
describe the console: which address ranges exist, what the hardware registers
are called, and what each GTE (COP2) command number means.
"""

from __future__ import annotations

# (name, start, size, kind) -- kind: "ram" (uninitialised RAM), "io" (volatile
# hardware registers), "rom" (BIOS, contents unknown), "scratch" (1 KB fast RAM)
REGIONS = [
    ("kernel_ram", 0x80000000, 0x10000, "ram"),        # BIOS/kernel area of main RAM
    ("scratchpad", 0x1F800000, 0x400, "scratch"),
    ("io", 0x1F801000, 0x2000, "io"),
    ("bios_rom", 0xBFC00000, 0x80000, "rom"),
    ("cache_ctrl", 0xFFFE0000, 0x200, "io"),
]
NET_YAROZE_LIBPS = ("libps_resident", 0x80010000, 0x80000, "ram")   # 0x80010000-0x8008FFFF

# Hardware registers: (address, name, comment)
IO_REGISTERS: list[tuple[int, str, str]] = [
    (0x1F801040, "JOY_DATA", "controller / memory card data"),
    (0x1F801044, "JOY_STAT", "controller status"),
    (0x1F801048, "JOY_MODE", "controller mode"),
    (0x1F80104A, "JOY_CTRL", "controller control"),
    (0x1F80104E, "JOY_BAUD", "controller baud"),
    (0x1F801050, "SIO_DATA", "serial port data"),
    (0x1F801060, "RAM_SIZE", "memory control"),
    (0x1F801070, "I_STAT", "interrupt status"),
    (0x1F801074, "I_MASK", "interrupt mask"),
    (0x1F8010F0, "DPCR", "DMA control"),
    (0x1F8010F4, "DICR", "DMA interrupt"),
    (0x1F801800, "CD_INDEX", "CD-ROM index/status"),
    (0x1F801801, "CD_REG1", "CD-ROM command/response"),
    (0x1F801802, "CD_REG2", "CD-ROM parameter/data"),
    (0x1F801803, "CD_REG3", "CD-ROM request/interrupt"),
    (0x1F801810, "GPU_GP0", "GPU render commands (write) / GPUREAD (read)"),
    (0x1F801814, "GPU_GP1", "GPU display control (write) / GPUSTAT (read)"),
    (0x1F801820, "MDEC_DATA", "MDEC command/data"),
    (0x1F801824, "MDEC_CTRL", "MDEC status/control"),
    (0x1F801C00, "SPU_VOICES", "SPU voice registers (24 x 16 bytes)"),
    (0x1F801D80, "SPU_MAIN_VOL", "SPU main volume"),
    (0xFFFE0130, "CACHE_CTRL", "cache control"),
]
_DMA = ["MDEC_IN", "MDEC_OUT", "GPU", "CDROM", "SPU", "PIO", "OTC"]
for _ch, _name in enumerate(_DMA):
    for _off, _reg in ((0, "MADR"), (4, "BCR"), (8, "CHCR")):
        IO_REGISTERS.append((0x1F801080 + 0x10 * _ch + _off, f"DMA{_ch}_{_name}_{_reg}", f"DMA channel {_ch} ({_name})"))
for _t in range(3):
    for _off, _reg in ((0, "COUNT"), (4, "MODE"), (8, "TARGET")):
        IO_REGISTERS.append((0x1F801100 + 0x10 * _t + _off, f"TIMER{_t}_{_reg}", f"root counter {_t}"))
IO_REGISTERS.sort()

# Labels outside the I/O block
LABELS = [
    (0x1F800000, "SCRATCHPAD", "1 KB fast RAM (D-cache used as RAM)"),
    (0xBFC00000, "BIOS_RESET", "reset vector"),
]

# GTE command number (low 6 bits of a COP2 command word) -> (name, meaning)
GTE_COMMANDS = {
    0x01: ("RTPS", "rotate, translate, perspective-project V0"),
    0x06: ("NCLIP", "normal clip: winding / back-face test"),
    0x0C: ("OP", "outer product"),
    0x10: ("DPCS", "depth cue single colour"),
    0x11: ("INTPL", "interpolate toward far colour"),
    0x12: ("MVMVA", "matrix x vector + vector"),
    0x13: ("NCDS", "normal colour depth-cue, single"),
    0x14: ("CDP", "colour depth-cue"),
    0x16: ("NCDT", "normal colour depth-cue, triple"),
    0x1B: ("NCCS", "normal colour colour, single"),
    0x1C: ("CC", "colour colour"),
    0x1E: ("NCS", "normal colour, single"),
    0x20: ("NCT", "normal colour, triple"),
    0x28: ("SQR", "square of IR"),
    0x29: ("DCPL", "depth-cue colour light"),
    0x2A: ("DPCT", "depth cue, triple"),
    0x2D: ("AVSZ3", "average 3 Z -> OTZ"),
    0x2E: ("AVSZ4", "average 4 Z -> OTZ"),
    0x30: ("RTPT", "rotate, translate, perspective-project V0..V2"),
    0x3D: ("GPF", "general purpose interpolation"),
    0x3E: ("GPL", "general purpose interpolation + base"),
    0x3F: ("NCCT", "normal colour colour, triple"),
}


def gte_command(word: int):
    """If a 32-bit instruction word is a GTE command (COP2 with CO bit), return
    (name, meaning, sf, lm) else None. sf = shift fraction, lm = clamp IR >= 0."""
    if (word >> 26) != 0x12 or not (word >> 25) & 1:
        return None
    info = GTE_COMMANDS.get(word & 0x3F)
    if info is None:
        return None
    return info[0], info[1], (word >> 19) & 1, (word >> 10) & 1


def parse_symbol_list(text: str) -> list[tuple[str, int]]:
    """Read (name, address) pairs from a user-supplied symbol file.

    Accepts assembler ``.set NAME, 0xADDR`` lines (the form psxsdk's
    playstation-yaroze-symusr.S uses for the Net Yaroze libps entry points) and
    plain ``NAME ADDR`` / ``ADDR NAME`` lines. Anything else is ignored.
    """
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(".set"):
            parts = [p.strip() for p in line[4:].split(",")]
        else:
            parts = line.split()
        if len(parts) != 2:
            continue
        a, b = parts
        for name, addr in ((a, b), (b, a)):
            try:
                value = int(addr, 16) if addr.lower().startswith("0x") else int(addr, 16) if len(addr) == 8 else None
            except ValueError:
                value = None
            if value is not None and name.replace("_", "").isalnum() and not name[0].isdigit():
                out.append((name, value))
                break
    return out


def symbols_tsv(net_yaroze: bool = False) -> str:
    """Region and label lines in the simple tab-separated form PsxSetup.java reads."""
    lines = []
    regions = REGIONS + ([NET_YAROZE_LIBPS] if net_yaroze else [])
    for name, start, size, kind in regions:
        lines.append(f"region\t{name}\t{start:08X}\t{size:X}\t{kind}")
    for addr, name, comment in IO_REGISTERS + LABELS:
        lines.append(f"label\t{name}\t{addr:08X}\t{comment}")
    for num, (name, meaning) in sorted(GTE_COMMANDS.items()):
        lines.append(f"gte\t{name}\t{num:02X}\t{meaning}")
    return "\n".join(lines) + "\n"
