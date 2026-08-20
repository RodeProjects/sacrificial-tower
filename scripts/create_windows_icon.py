from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png_frame(source: QImage, size: int) -> bytes:
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    maximum_extent = max(1, round(size * 0.92))
    scaled = source.scaled(
        maximum_extent,
        maximum_extent,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(canvas)
    painter.drawImage(
        (size - scaled.width()) // 2,
        (size - scaled.height()) // 2,
        scaled,
    )
    painter.end()

    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError("Der PNG-Puffer konnte nicht geöffnet werden.")
    if not canvas.save(buffer, "PNG"):
        raise OSError(f"Die Icon-Ebene {size}x{size} konnte nicht erzeugt werden.")
    return bytes(buffer.data())


def create_icon(source_path: Path, target_path: Path) -> None:
    source = QImage(str(source_path))
    if source.isNull():
        raise ValueError(f"Das Quellbild konnte nicht gelesen werden: {source_path}")
    frames = [(size, render_png_frame(source, size)) for size in ICON_SIZES]
    directory_size = 6 + 16 * len(frames)
    offset = directory_size
    entries: list[bytes] = []
    payloads: list[bytes] = []
    for size, payload in frames:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                0 if size == 256 else size,
                0 if size == 256 else size,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        payloads.append(payload)
        offset += len(payload)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(
        struct.pack("<HHH", 0, 1, len(frames))
        + b"".join(entries)
        + b"".join(payloads)
    )


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    source_path = (
        project_root
        / "src"
        / "cooling_tower"
        / "gui"
        / "assets"
        / "icon_tower_render.png"
    )
    target_path = source_path.with_name("app.ico")
    create_icon(source_path, target_path)
    print(target_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
