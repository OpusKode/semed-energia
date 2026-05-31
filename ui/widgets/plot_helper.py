"""
Helper para criacao consistente de PlotWidgets em toda a UI.

Padroniza:
- Zoom e pan DESABILITADOS (graficos sao somente leitura)
- Menu de contexto desabilitado
- Botoes de auto-range escondidos
- Grid sutil no eixo Y
- Y iniciando em zero quando os valores sao positivos
- Card wrapper com titulo + plot
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy

import pyqtgraph as pg

from ui.theme import BG_CARD, TEXT_MUTED, BORDER, ACCENT


# Configuracao global (faz uma vez por processo)
pg.setConfigOption("background", BG_CARD)
pg.setConfigOption("foreground", TEXT_MUTED)
pg.setConfigOption("antialias", True)


def configurar_plot(pw: pg.PlotWidget):
    """Aplica defaults visuais e bloqueia zoom/pan."""
    # Bloqueia interacao (zoom/pan)
    pw.setMouseEnabled(x=False, y=False)
    pw.setMenuEnabled(False)
    plot_item = pw.getPlotItem()
    plot_item.hideButtons()
    plot_item.setMouseEnabled(x=False, y=False)
    plot_item.showGrid(x=False, y=True, alpha=0.15)
    # Margens menos gritantes
    pw.setContentsMargins(0, 4, 4, 0)
    # Eixos
    for eixo_nome in ("bottom", "left"):
        ax = pw.getAxis(eixo_nome)
        ax.setTextPen(TEXT_MUTED)
        ax.setPen(BORDER)
    return pw


def criar_card_plot(titulo: str, altura: int = 220) -> tuple[QFrame, pg.PlotWidget]:
    """Cria um QFrame "Card" com um PlotWidget ja configurado."""
    frame = QFrame()
    frame.setObjectName("Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)

    lbl = QLabel(titulo)
    lbl.setObjectName("SectionTitle")
    lay.addWidget(lbl)

    pw = pg.PlotWidget()
    configurar_plot(pw)
    pw.setMinimumHeight(altura)
    lay.addWidget(pw)

    lbl_empty = QLabel("Sem dados para o período selecionado")
    lbl_empty.setAlignment(Qt.AlignCenter)
    lbl_empty.setStyleSheet(
        "color: #6E6B67; font-style: italic; font-size: 11px;"
        " background: transparent; border: none;"
    )
    lbl_empty.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lbl_empty.setVisible(False)
    lay.addWidget(lbl_empty)

    frame.plot = pw
    frame.titulo = lbl
    frame.lbl_empty = lbl_empty
    return frame


def limpar(pw: pg.PlotWidget):
    """Reseta o plot mantendo a configuracao (ticks, grid, etc)."""
    pw.clear()
    pw.getAxis("bottom").setTicks(None)
    pw.getAxis("left").setTicks(None)
    pw.setLabel("left", "")
    pw.setLabel("bottom", "")
    # Reset inversoes de eixo (caso um plot anterior tenha chamado invertY/X)
    pw.getPlotItem().invertY(False)
    pw.getPlotItem().invertX(False)


def ajustar_y_com_zero(pw: pg.PlotWidget, valores: list[float], margem: float = 0.10):
    """
    Fixa Y de 0 ate max*1.1 quando todos valores sao >= 0.
    Se ha negativos, usa min*1.1 .. max*1.1.
    """
    if not valores:
        pw.enableAutoRange(axis="y", enable=True)
        return
    lo, hi = min(valores), max(valores)
    if hi == lo:
        hi = lo + 1
    if lo >= 0:
        top = hi * (1 + margem) if hi > 0 else 1.0
        pw.setYRange(0, top, padding=0)
    else:
        span = hi - lo
        pw.setYRange(lo - span * margem, hi + span * margem, padding=0)


def fixar_x_categorico(pw: pg.PlotWidget, n: int, margem: float = 0.5):
    """Limita o X para nao sobrar espaco quando usamos ticks categoricos."""
    if n <= 0:
        return
    pw.setXRange(-margem, n - 1 + margem, padding=0)


def ajustar_x_com_zero(pw: pg.PlotWidget, valores: list[float], margem: float = 0.10):
    """Versao para barras horizontais: fixa o eixo X (valor) a partir de zero."""
    if not valores:
        pw.enableAutoRange(axis="x", enable=True)
        return
    lo, hi = min(valores), max(valores)
    if hi == lo:
        hi = lo + 1
    if lo >= 0:
        pw.setXRange(0, hi * (1 + margem), padding=0)
    else:
        span = hi - lo
        pw.setXRange(lo - span * margem, hi + span * margem, padding=0)


def fixar_y_categorico(pw: pg.PlotWidget, n: int, margem: float = 0.5):
    """Fixa o Y para barras horizontais com categorias discretas."""
    if n <= 0:
        return
    pw.setYRange(-margem, n - 1 + margem, padding=0)
