"""
Icones Lucide (https://lucide.dev) incorporados como SVG inline.

Uso:
    from ui.widgets.icons import lucide_icon, LUCIDE_ICONS
    btn.setIcon(lucide_icon("upload"))
    btn.setIcon(lucide_icon("check-circle", color="#7FAE6E", size=20))

Lucide é licenciado sob ISC — uso livre.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer

from ui.theme import TEXT_PRIMARY


# ---------------------------------------------------------------
# Mapa de icones — cada entrada contem apenas o miolo do SVG
# (os paths/lines/polylines), a wrapper <svg> e adicionada dinamicamente.
# stroke="currentColor" permite trocar a cor em runtime.
# ---------------------------------------------------------------

_ICON_PATHS = {
    # Navegacao principal
    "upload":        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "upload-cloud":  '<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M12 12v9"/><path d="m16 16-4-4-4 4"/>',
    "layers":        '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.91a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "building-2":    '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
    "bar-chart-3":   '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
    "check-circle":  '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',

    # Navegacao / botoes
    "arrow-left":    '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "arrow-right":   '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',

    # Acoes
    "play":          '<polygon points="5 3 19 12 5 21 5 3"/>',
    "folder-open":   '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.93a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2"/>',
    "trash-2":       '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
    "refresh-cw":    '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',

    # Feedback
    "check":         '<polyline points="20 6 9 17 4 12"/>',
    "x":             '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "alert-triangle":'<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "info":          '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',

    # Diversos
    "file-text":     '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/>',
    "search":        '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "filter":        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "zap":           '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "download":      '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "file-spreadsheet":'<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><polyline points="14 2 14 8 20 8"/><path d="M8 13h2"/><path d="M8 17h2"/><path d="M14 13h2"/><path d="M14 17h2"/>',
}


def _svg_wrap(inner: str, stroke: str = "currentColor", stroke_width: float = 2.0) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{stroke}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )


def _render_pixmap(name: str, color: str, size: int) -> QPixmap:
    svg = _svg_wrap(_ICON_PATHS[name], stroke=color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return pm


@lru_cache(maxsize=256)
def lucide_icon(name: str, color: str = TEXT_PRIMARY, size: int = 18,
                disabled_color: str | None = None) -> QIcon:
    """Retorna um QIcon Lucide com cor/tamanho customizados.

    Se `disabled_color` for informado, registra tambem um pixmap para o
    modo Disabled do QIcon, evitando que o icone fique com cor errada
    quando o botao esta desabilitado.
    """
    if name not in _ICON_PATHS:
        return QIcon()
    icon = QIcon(_render_pixmap(name, color, size))
    if disabled_color:
        icon.addPixmap(_render_pixmap(name, disabled_color, size), QIcon.Disabled)
    return icon


def lucide_pixmap(name: str, color: str = TEXT_PRIMARY, size: int = 48) -> QPixmap:
    """Retorna QPixmap (util para QLabel com setPixmap)."""
    icon = lucide_icon(name, color, size)
    return icon.pixmap(size, size)
