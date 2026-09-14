"""Generates a placeholder LoadCraft icon (solid accent-blue square).

Stdlib only: hand-rolls the PNG so the build needs no image library.
Replace with a real icon later - the build only needs a same-named PNG.
"""

import struct
import sys
import zlib


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
    make_png(sys.argv[1] if len(sys.argv) > 1 else "LoadCraft.png")
