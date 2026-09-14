"""Generates the LoadCraft icon assets.

Stdlib only: hand-rolls the PNG so the build needs no image library.

- make_icon.py <out.png>          placeholder icon (solid accent-blue square)
- make_icon.py <out.ico> <in.png> wrap an existing PNG into a Windows .ico
  (PNG-compressed entry, Vista+ format). Regenerate it whenever the PNG
  changes: dist-tools/LoadCraft.ico is built from LoadCraft.png and the
  Windows package embeds it with pyinstaller --icon.
"""

import struct
import sys
import zlib


def ico_from_png(out_path: str, png_path: str) -> None:
    """Embeds a PNG in a single-image ICO container (no re-encoding)."""
    with open(png_path, "rb") as fh:
        png = fh.read()
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{png_path} is not a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if width != height or not (16 <= width <= 256):
        raise SystemExit("the icon must be square, 16-256 px")
    size = width if width < 256 else 0  # 0 encodes 256 in the ICO header
    icondir = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 22)
    with open(out_path, "wb") as fh:
        fh.write(icondir + entry + png)


def chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(
        ">I", zlib.crc32(body) & 0xFFFFFFFF
    )


def make_png(path: str, size: int = 256, rgb=(45, 163, 255)) -> None:
    raw = b"".join(
        b"\x00" + bytes(rgb) * size for _ in range(size)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as fh:
        fh.write(png)


if __name__ == "__main__":
    if len(sys.argv) > 2:
        ico_from_png(sys.argv[1], sys.argv[2])
    else:
        make_png(sys.argv[1] if len(sys.argv) > 1 else "LoadCraft.png")
