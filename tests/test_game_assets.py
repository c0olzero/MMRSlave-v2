"""The game-file reader: archive index, texture decoding, minimap placement."""

import struct

import numpy as np

from mmrslave.game_assets import Vpk, decode_vtex, minimap_window

OVERVIEW = b"""dota
{
\tmaterial materials/overviews/dota.vmat
\tsimple_material materials/overviews/dota_minimal.vmat
\tpos_x -9472
\tpos_y 9472
\tscale 18.500
}
"""


def _vtex(w: int, h: int, fmt: int, pixels: bytes) -> bytes:
    """A minimal compiled texture: header, one DATA block, then the pixels."""
    data = struct.pack("<HH4fHHHBBIII", 1, 0, 0, 0, 0, 0, w, h, 1, fmt, 1, 0, 0, 0)
    header = struct.pack("<IHHII", 0, 12, 1, 8, 1)
    block = b"DATA" + struct.pack("<II", 8, len(data))   # data starts right after this entry
    return header + block + data + pixels


def test_decode_bgra_swaps_to_rgba():
    px = bytes([10, 20, 30, 255]) * 4                       # B, G, R, A
    img = decode_vtex(_vtex(2, 2, 28, px))
    assert img.shape == (2, 2, 4)
    assert img[0, 0].tolist() == [30, 20, 10, 255]


def test_decode_dxt5_block():
    alpha = bytes([255, 0]) + bytes(6)                      # every pixel uses alpha endpoint 0
    red, blue = 0xF800, 0x001F
    colour = struct.pack("<HHI", red, blue, 0x55555555)     # every pixel uses colour endpoint 1
    img = decode_vtex(_vtex(4, 4, 2, alpha + colour))
    assert img.shape == (4, 4, 4)
    assert img[2, 3].tolist() == [0, 0, 255, 255]


def test_vpk_reads_embedded_file(tmp_path):
    body = OVERVIEW
    tree = (b"txt\0resource/overviews\0dota\0"
            + struct.pack("<IHHIIH", 0, 0, 0x7FFF, 0, len(body), 0xFFFF) + b"\0\0\0")
    path = tmp_path / "pak01_dir.vpk"
    path.write_bytes(struct.pack("<7I", 0x55AA1234, 2, len(tree), len(body), 0, 0, 0) + tree + body)
    vpk = Vpk(path)
    assert list(vpk.entries) == ["resource/overviews/dota.txt"]
    assert vpk.read("resource/overviews/dota.txt") == body


def test_minimap_window_in_replay_coordinates():
    win = minimap_window(OVERVIEW.decode())
    # 1024 overview pixels x 18.5 units, starting at world -9472 (+16384 replay offset).
    assert win == {"x0": 6912.0, "y0": 6912.0, "size": 18944.0}
    # Both fountains (gem's map constants) land inside the picture, near opposite corners.
    for (x, y), corner in (((8928, 9446), (0.09, 0.13)), ((23792, 23232), (0.89, 0.86))):
        fx, fy = (x - win["x0"]) / win["size"], (y - win["y0"]) / win["size"]
        assert np.allclose((fx, fy), corner, atol=0.02)
