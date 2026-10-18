"""A small stroke icon set (24 px grid, drawn for this app) rendered through QtSvg in any colour."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5h4v5"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5 15.5 12 10 15.5z"/>',
    "boardroom": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>'
                 '<path d="M3 13h18"/>',
    "revenue": '<path d="M4 20h16"/><path d="M6 16l4-4 3 3 5-6"/><path d="M15 9h3v3"/>',
    "fpa": '<path d="M12 4v16"/><path d="M5 8h14"/><path d="M5 8l-2.5 6a3 3 0 0 0 5 0z"/><path d="M19 8l-2.5 6a3 3 0 0 0 5 0z"/>'
           '<path d="M8 20h8"/>',
    "statements": '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 12h5M10 16h5"/>',
    "lab": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/>'
           '<circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "workbench": '<path d="M12 3 20 7.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12 4 7.5M12 12v9"/>',
    "risk": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "invest": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/>'
              '<path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
    "academy": '<path d="M2.5 9 12 4.5 21.5 9 12 13.5z"/><path d="M6 11v5c0 1.5 2.7 3 6 3s6-1.5 6-3v-5"/><path d="M21.5 9v5"/>',
    "excel": '<rect x="3.5" y="4" width="17" height="16" rx="2"/><path d="M3.5 9.5h17M3.5 15h17M9.5 4v16"/>',
    "capstone": '<circle cx="12" cy="9" r="5"/><path d="M8.5 13 7 21l5-2.5 5 2.5-1.5-8"/>',
    "reports": '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1'
                'M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7"/>',
    "alert": '<path d="M12 3.5 22 20H2z"/><path d="M12 10v4.5M12 17.5h0"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5h0"/>',
    "star": '<path d="M12 3l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.9z"/>',
    "trend-up": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "trend-down": '<path d="m3 7 6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.5-3.5 3.2-5.5 6.5-5.5s6 2 6.5 5.5"/>'
             '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.8c2 .7 3.2 2.5 3.5 5.2"/>',
    "wrench": '<path d="M14.5 6.5a4.5 4.5 0 0 0 5.6 5.6L13 19.2a2.5 2.5 0 0 1-3.5-3.5l7.1-7.1"/><path d="M14.5 6.5 17 4l3 3-2.5 2.5"/>',
    "megaphone": '<path d="M3 10v4h3l9 5V5L6 10z"/><path d="M18.5 9a4 4 0 0 1 0 6"/><path d="M6 14l1.5 6h3L9 15"/>',
    "building": '<path d="M4 21V5l8-2v18M12 21V8l8 2v11"/><path d="M7 8h2M7 12h2M7 16h2M15 13h2M15 17h2"/><path d="M2 21h20"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
    "glossary": '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
    "flag": '<path d="M5 21V4"/><path d="M5 4h11l-2 4 2 4H5"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    "thermometer": '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
    "cash": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/><path d="M6 9.5v5M18 9.5v5"/>',
}


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18, stroke: float = 1.8, dpr: float = 2.0) -> QPixmap:
    body = _P.get(name, _P["info"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, color: str, size: int = 18, active_color: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, active_color or color, size), QIcon.Selected, QIcon.Off)
    ic.addPixmap(pixmap(name, active_color or color, size), QIcon.Active, QIcon.Off)
    return ic


def names() -> list[str]:
    return sorted(_P)
