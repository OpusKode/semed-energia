"""Barra de titulo customizada, minimalista, inspirada no Claude desktop.

Uso:
    self.setWindowFlags(Qt.FramelessWindowHint)
    bar = TitleBar(self, "SEMED Energia")
    # adicione `bar` no topo do layout central.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QSize, QEvent
from PySide6.QtGui import QMouseEvent, QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
)

from ui.theme import (
    BG_SIDEBAR, BG_HOVER, BORDER, TEXT_SECONDARY, TEXT_MUTED, ACCENT, ERROR,
)


# ---------- icones desenhados em vetor (sem depender de fontes) ----------
def _icon_min(color: str, size: int = 10) -> QIcon:
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, False)
    pen = QPen(QColor(color)); pen.setWidth(1)
    p.setPen(pen)
    y = size // 2
    p.drawLine(1, y, size - 2, y)
    p.end()
    return QIcon(pm)


def _icon_max(color: str, size: int = 10) -> QIcon:
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, False)
    pen = QPen(QColor(color)); pen.setWidth(1)
    p.setPen(pen)
    p.drawRect(1, 1, size - 3, size - 3)
    p.end()
    return QIcon(pm)


def _icon_restore(color: str, size: int = 10) -> QIcon:
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, False)
    pen = QPen(QColor(color)); pen.setWidth(1)
    p.setPen(pen)
    # dois quadrados sobrepostos
    p.drawRect(2, 0, size - 4, size - 4)
    p.drawRect(0, 2, size - 4, size - 4)
    p.end()
    return QIcon(pm)


def _icon_close(color: str, size: int = 10) -> QIcon:
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color)); pen.setWidth(1)
    p.setPen(pen)
    p.drawLine(1, 1, size - 2, size - 2)
    p.drawLine(size - 2, 1, 1, size - 2)
    p.end()
    return QIcon(pm)


class TitleBar(QWidget):
    """Barra fina (36 px) com titulo discreto e botoes min/max/close minimalistas."""

    HEIGHT = 36

    def __init__(self, window: QWidget, title: str = ""):
        super().__init__(window)
        self._win = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(self._style())
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 6, 0)
        lay.setSpacing(8)

        # Ponto de sotaque (acento laranja) a esquerda, como um "app dot"
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background: {ACCENT}; border-radius: 4px;"
        )
        lay.addWidget(dot, 0, Qt.AlignVCenter)

        # titulo discreto
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("TitleBarTitle")
        self.lbl_title.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;"
        )
        lay.addWidget(self.lbl_title, 0, Qt.AlignVCenter)

        lay.addStretch(1)

        # botoes
        self.btn_min = self._make_btn(_icon_min(TEXT_SECONDARY),
                                      hover_bg=BG_HOVER,
                                      tip="Minimizar")
        self.btn_max = self._make_btn(_icon_max(TEXT_SECONDARY),
                                      hover_bg=BG_HOVER,
                                      tip="Maximizar")
        self.btn_close = self._make_btn(_icon_close(TEXT_SECONDARY),
                                        hover_bg=ERROR,
                                        tip="Fechar",
                                        danger=True)

        self.btn_min.clicked.connect(self._win.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(self._win.close)

        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_close)

        self._win.installEventFilter(self)

    # -------------------- visual --------------------
    def _style(self) -> str:
        return f"""
            QWidget#TitleBar {{
                background-color: {BG_SIDEBAR};
                border-bottom: 1px solid {BORDER};
            }}
        """

    def _make_btn(self, icon: QIcon, hover_bg: str, tip: str,
                  danger: bool = False) -> QPushButton:
        b = QPushButton()
        b.setIcon(icon)
        b.setIconSize(QSize(10, 10))
        b.setFixedSize(36, 26)
        b.setCursor(Qt.PointingHandCursor)
        b.setToolTip(tip)
        fg = "#FFFFFF" if danger else TEXT_SECONDARY
        b.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                color: {fg};
            }}
            QPushButton:hover {{
                background: {hover_bg};
                color: {fg};
            }}
        """)
        return b

    # -------------------- comportamento --------------------
    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
            self.btn_max.setIcon(_icon_max(TEXT_SECONDARY))
        else:
            self._win.showMaximized()
            self.btn_max.setIcon(_icon_restore(TEXT_SECONDARY))

    def eventFilter(self, obj, ev):
        if obj is self._win and ev.type() == QEvent.WindowStateChange:
            if self._win.isMaximized():
                self.btn_max.setIcon(_icon_restore(TEXT_SECONDARY))
            else:
                self.btn_max.setIcon(_icon_max(TEXT_SECONDARY))
        return False

    # ----- arrastar a janela clicando na barra -----
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - \
                             self._win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            if self._win.isMaximized():
                # desmaximiza ancorando o cursor na barra
                self._win.showNormal()
                self._drag_pos = QPoint(self._win.width() // 2, self.HEIGHT // 2)
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._toggle_max()
