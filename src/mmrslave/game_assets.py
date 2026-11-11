"""The real minimap and hero icons, read from the player's own Dota 2 install.

Valve's art never ships with MMRSlave. `extract` copies it out of the game's archive
(game/dota/pak01_dir.vpk) into data_dir/game_assets as PNGs, and copies it again after a
game update. When the install can't be found the dashboard falls back to a drawn map.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any, Callable

import numpy as np

from mmrslave.config import Settings

# Replay positions are Source 2 world units shifted by +16384 (the same frame as gem
# and features.MAP_CX); the game's overview files use plain world units.
WORLD_OFFSET = 16384
# An overview's `scale` is world units per pixel of a 1024-pixel-wide overview,
# whatever the texture's real resolution.
OVERVIEW_PIXELS = 1024
# Bump when the extracted files change shape, so old copies are replaced.
FORMAT_VERSION = 3       # 2: item icons; 3: item icon colours fixed (YCoCg)

ICON_RE = re.compile(r"panorama/images/heroes/icons/(npc_dota_hero_\w+?)_png\.vtex_c")
ITEM_ICON_RE = re.compile(r"panorama/images/items/(\w+?)_png\.vtex_c")


def assets_dir(s: Settings) -> Path:
    return s.data_dir / "game_assets"


# ------------------------------------------------------------------ finding the game

def _steam_libraries() -> list[Path]:
    roots: list[Path] = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
    except (ImportError, OSError):
        pass
    roots += [Path("C:/Program Files (x86)/Steam"), Path.home() / ".steam/steam", Path.home() / ".local/share/Steam"]
    libs: list[Path] = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            text = vdf.read_text(encoding="utf-8", errors="replace")
            libs += [Path(m.group(1).replace("\\\\", "\\")) for m in re.finditer(r'"path"\s+"([^"]+)"', text)]
        libs.append(root)
    return list(dict.fromkeys(libs))


def find_game_dir(s: Settings) -> Path | None:
    """The `game/dota` folder that holds pak01_dir.vpk."""
    candidates = [Path(s.dota_dir)] if s.dota_dir else []
    candidates.append(Path(s.local_replays).parent)
    candidates += [lib / "steamapps" / "common" / "dota 2 beta" / "game" / "dota" for lib in _steam_libraries()]
    return next((c for c in candidates if (c / "pak01_dir.vpk").is_file()), None)


# ------------------------------------------------------------------ reading the archive

class Vpk:
    """Read-only access to a Valve pak: the _dir.vpk index plus its numbered archives."""

    def __init__(self, dir_path: Path):
        self.path = Path(dir_path)
        with open(self.path, "rb") as f:
            sig, version, tree_size = struct.unpack("<III", f.read(12))
            if sig != 0x55AA1234:
                raise ValueError(f"{self.path} is not a VPK file")
            header = 12 + (16 if version == 2 else 0)
            f.seek(header)
            tree = f.read(tree_size)
        self._embedded_start = header + tree_size   # where archive 0x7FFF's data begins
        self.entries: dict[str, tuple[int, int, int, bytes]] = {}
        i = 0

        def cstr() -> str:
            nonlocal i
            j = tree.index(b"\0", i)
            text = tree[i:j].decode("utf-8", "replace")
            i = j + 1
            return text

        while ext := cstr():
            while folder := cstr():
                while name := cstr():
                    _crc, preload, archive, offset, length, _end = struct.unpack_from("<IHHIIH", tree, i)
                    i += 18
                    path = f"{name}.{ext}" if folder == " " else f"{folder}/{name}.{ext}"
                    self.entries[path] = (archive, offset, length, tree[i:i + preload])
                    i += preload

    def read(self, name: str) -> bytes:
        archive, offset, length, preload = self.entries[name]
        if length == 0:
            return preload
        if archive == 0x7FFF:
            path, base = self.path, self._embedded_start
        else:
            path, base = self.path.with_name(self.path.name.replace("_dir.vpk", f"_{archive:03d}.vpk")), 0
        with open(path, "rb") as f:
            f.seek(base + offset)
            return preload + f.read(length)


# ------------------------------------------------------------------ decoding textures

def decode_vtex(buf: bytes) -> np.ndarray:
    """The full-size image of a compiled Source 2 texture (.vtex_c), as RGBA uint8 (h, w, 4).
    Handles the formats the minimap and hero icons use: RGBA8888, BGRA8888 and DXT5."""
    _size, _hv, _tv, block_offset, n_blocks = struct.unpack_from("<IHHII", buf, 0)
    p = 8 + block_offset
    for _ in range(n_blocks):
        kind = buf[p:p + 4]
        rel, size = struct.unpack_from("<II", buf, p + 4)
        start = p + 4 + rel
        if kind == b"DATA":
            w, h = struct.unpack_from("<HH", buf, start + 20)
            fmt = buf[start + 26]
            extra_rel, n_extra = struct.unpack_from("<II", buf, start + 32)
            for e in range(n_extra):
                if struct.unpack_from("<I", buf, start + 32 + extra_rel + 12 * e)[0] == 4:
                    raise ValueError("compressed mip levels aren't supported")
            # Pixel data follows the resource blocks, smallest mip first, so the full-size
            # image is at the very end.
            pixels = buf[start + size:]
            if fmt in (4, 28):                      # RGBA8888, BGRA8888
                a = np.frombuffer(pixels[len(pixels) - w * h * 4:], np.uint8).reshape(h, w, 4)
                return np.ascontiguousarray(a[..., [2, 1, 0, 3]] if fmt == 28 else a)
            if fmt == 2:                            # DXT5
                rgba = _dxt5(pixels[len(pixels) - ((w + 3) // 4) * ((h + 3) // 4) * 16:], w, h)
                # Item icons are stored as YCoCg in DXT5 (the compiler notes "YCoCg Conversion");
                # without converting back they come out green and yellow.
                return _from_ycocg(rgba) if b"YCoCg Conv" in buf[:start] else rgba
            raise ValueError(f"texture format {fmt} isn't supported")
        p += 12
    raise ValueError("no texture data in file")


def _from_ycocg(px: np.ndarray) -> np.ndarray:
    """Scaled YCoCg-DXT5 (Co in red, Cg in green, scale in blue, luma in alpha) to opaque RGBA."""
    p = px.astype(np.int32)
    scale = (p[..., 2] >> 3) + 1
    co = (p[..., 0] - 128) // scale
    cg = (p[..., 1] - 128) // scale
    y = p[..., 3]
    out = np.stack([y + co - cg, y + cg, y - co - cg, np.full_like(y, 255)], -1)
    return np.clip(out, 0, 255).astype(np.uint8)


def _dxt5(buf: bytes, w: int, h: int) -> np.ndarray:
    bw, bh = (w + 3) // 4, (h + 3) // 4
    blk = np.frombuffer(buf, np.uint8)[:bw * bh * 16].reshape(-1, 16)
    # Alpha: two endpoints and 16 three-bit indices.
    a0, a1 = blk[:, 0].astype(np.int32), blk[:, 1].astype(np.int32)
    abits = np.zeros(len(blk), np.uint64)
    for k in range(6):
        abits |= blk[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    aidx = np.stack([(abits >> np.uint64(3 * k)) & np.uint64(7) for k in range(16)], 1).astype(np.int64)
    apal = np.zeros((len(blk), 8), np.int32)
    apal[:, 0], apal[:, 1] = a0, a1
    for k in range(1, 7):                       # a0 > a1: six blended steps
        apal[:, k + 1] = ((7 - k) * a0 + k * a1) // 7
    five = a0 <= a1                             # otherwise four steps, then 0 and 255
    for k in range(1, 5):
        apal[five, k + 1] = ((5 - k) * a0[five] + k * a1[five]) // 5
    apal[five, 6], apal[five, 7] = 0, 255
    alpha = np.take_along_axis(apal, aidx, 1)
    # Colour: two RGB565 endpoints and 16 two-bit indices.
    def rgb565(c: np.ndarray) -> np.ndarray:
        return np.stack([(c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31], -1)
    c0 = rgb565(blk[:, 8].astype(np.int32) | blk[:, 9].astype(np.int32) << 8)
    c1 = rgb565(blk[:, 10].astype(np.int32) | blk[:, 11].astype(np.int32) << 8)
    cpal = np.stack([c0, c1, (2 * c0 + c1) // 3, (c0 + 2 * c1) // 3], 1)
    cbits = blk[:, 12:16].astype(np.uint32) << np.array([0, 8, 16, 24], np.uint32)
    cbits = cbits[:, 0] | cbits[:, 1] | cbits[:, 2] | cbits[:, 3]
    cidx = np.stack([(cbits >> np.uint32(2 * k)) & np.uint32(3) for k in range(16)], 1).astype(np.int64)
    rgb = np.take_along_axis(cpal, cidx[..., None].repeat(3, -1), 1)
    px = np.concatenate([rgb, alpha[..., None]], -1).astype(np.uint8).reshape(bh, bw, 4, 4, 4)
    return np.ascontiguousarray(px.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)[:h, :w])


def write_png(path: Path, rgba: np.ndarray) -> None:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ the minimap

def minimap_window(overview_text: str) -> dict[str, float]:
    """Where the minimap sits, in replay coordinates, from resource/overviews/dota.txt."""
    def num(key: str) -> float:
        m = re.search(rf"(?<![\w]){key}\s+(-?[\d.]+)", overview_text)
        if not m:
            raise ValueError(f"overview has no {key}")
        return float(m.group(1))
    size = OVERVIEW_PIXELS * num("scale")
    left, top = num("pos_x") + WORLD_OFFSET, num("pos_y") + WORLD_OFFSET
    return {"x0": left, "y0": top - size, "size": size}


def _minimap_texture(vpk: Vpk, overview_text: str) -> str:
    m = re.search(r"(?<![\w])material\s+(\S+\.vmat)", overview_text)
    if not m:
        raise ValueError("overview names no material")
    material = vpk.read(m.group(1) + "_c")
    for ref in re.findall(rb"materials/[\w/]+\.vtex", material):
        name = ref.decode() + "_c"
        if name in vpk.entries:
            return name
    raise ValueError(f"no texture found for {m.group(1)}")


# ------------------------------------------------------------------ extraction

def load_manifest(s: Settings) -> dict[str, Any] | None:
    path = assets_dir(s) / "manifest.json"
    try:
        man = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return man if (assets_dir(s) / man.get("minimap", {}).get("file", "-")).is_file() else None


def extract(s: Settings, force: bool = False, log: Callable[[str], None] = print) -> dict[str, Any] | None:
    """Copy the minimap and hero icons out of the game, unless the copy is already current.
    Returns the manifest, or None when there's nothing to show."""
    current = load_manifest(s)
    game = find_game_dir(s)
    if game is None:
        if current is None:
            log("Dota 2 install not found, so the board uses a drawn map. "
                "Set paths.dota_dir in mmrslave.toml to your 'game/dota' folder.")
        return current
    pak = game / "pak01_dir.vpk"
    source = {"pak": str(pak), "mtime": pak.stat().st_mtime, "format": FORMAT_VERSION}
    if current and current.get("source") == source and not force:
        return current

    vpk = Vpk(pak)
    out = assets_dir(s)
    (out / "heroes").mkdir(parents=True, exist_ok=True)
    (out / "items").mkdir(parents=True, exist_ok=True)
    overview = vpk.read("resource/overviews/dota.txt").decode("utf-8", "replace")
    window = minimap_window(overview)
    image = decode_vtex(vpk.read(_minimap_texture(vpk, overview)))
    write_png(out / "minimap.png", image)

    icons = items = 0
    for name in vpk.entries:
        m = ICON_RE.fullmatch(name)
        item = ITEM_ICON_RE.fullmatch(name)
        if not (m or item):
            continue
        try:
            image_px = decode_vtex(vpk.read(name))
        except ValueError:
            continue                    # a handful of cosmetic icons use formats we don't read
        if m:
            write_png(out / "heroes" / f"{m.group(1)}.png", image_px)
            icons += 1
        else:
            write_png(out / "items" / f"{item.group(1)}.png", image_px)
            items += 1
    manifest = {"minimap": {"file": "minimap.png", "pixels": int(image.shape[1]), **window},
                "hero_icons": icons, "item_icons": items, "source": source}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    log(f"Copied the minimap ({image.shape[1]}px), {icons} hero icons and {items} item icons from {game}")
    return manifest


def item_icons(s: Settings) -> set[str]:
    folder = assets_dir(s) / "items"
    return {p.stem for p in folder.glob("*.png")} if folder.is_dir() else set()


def hero_icons(s: Settings) -> set[str]:
    folder = assets_dir(s) / "heroes"
    return {p.stem for p in folder.glob("*.png")} if folder.is_dir() else set()
