"""Application-owned animation drawn by Qt SVG, without Python frame callbacks."""
import math

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter


def _png_uri(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64,"+bytes(buffer.data().toBase64()).decode("ascii")


def busy_svg(background, width, height, *, elapsed_ms=0, protected=None):
    """Preserve the flowing waves, moving glow and light sweep as native SMIL."""
    duration, radius = 8, max(width, height)*.7
    begin = -((elapsed_ms % 8000)/1000)
    timing = f'dur="{duration}s" begin="{begin:.4f}s" repeatCount="indefinite"'
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        f'<radialGradient id="glow" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="{radius}"><stop stop-color="#2d99eb" stop-opacity=".333"/><stop offset=".5" stop-color="#35bec3" stop-opacity=".176"/><stop offset="1" stop-color="#35bec3" stop-opacity="0"/></radialGradient>',
        f'<linearGradient id="light" gradientUnits="userSpaceOnUse" x1="-200" y1="0" x2="200" y2="{height}"><stop stop-color="#64aada" stop-opacity="0"/><stop offset=".5" stop-color="#64beeb" stop-opacity=".165"/><stop offset="1" stop-color="#64aada" stop-opacity="0"/></linearGradient>']
    if protected is not None:
        mask = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        mask.fill(QColor(255, 255, 255, 87))
        painter = QPainter(mask)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillPath(protected, QColor(255, 255, 255, 6))
        painter.end()
        pieces.append(f'<mask id="intensity" maskUnits="userSpaceOnUse" x="0" y="0" width="{width}" height="{height}"><image width="{width}" height="{height}" xlink:href="{_png_uri(mask)}"/></mask>')
    pieces.extend(('</defs>', f'<image width="{width}" height="{height}" xlink:href="{_png_uri(background)}"/>',
        '<g mask="url(#intensity)">' if protected is not None else '<g>',
        f'<rect width="{width}" height="{height}" fill="#101721" fill-opacity=".451"/>'))
    values = ";".join(f"{width*(.5+.3*math.sin(math.tau*i/64)):.4f} {height*(.5+.25*math.cos(math.tau*i/64)):.4f}" for i in range(65))
    pieces.append(f'<g><animateTransform attributeName="transform" type="translate" values="{values}" {timing}/><circle r="{radius}" fill="url(#glow)"/></g>')
    pieces.append(f'<g><animateTransform attributeName="transform" type="translate" from="0 0" to="{-width} 0" {timing}/>')
    for band in range(1, 8):
        points = " ".join(f'{x:.2f},{height*band/8+math.sin(x/max(1,width)*math.tau+band*.55)*28:.3f}'
            for x in range(-24, 2*width+49, 24))
        pieces.append(f'<polyline points="{points}" fill="none" stroke="#7cd7ef" stroke-opacity=".188" stroke-width="1.2"/>')
    pieces.extend(('</g>', f'<g><animateTransform attributeName="transform" type="translate" from="-250 0" to="{width+250} 0" {timing}/><rect x="{-2*width}" width="{5*width}" height="{height}" fill="url(#light)"/></g>', '</g></svg>'))
    return "".join(pieces).encode("utf-8")
