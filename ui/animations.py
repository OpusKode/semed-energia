"""
Helpers de animacao e efeitos visuais para a UI.

Contem:
    - AnimatedBackground : widget com gradiente animado + orbes de luz ao fundo
    - AnimatedStackedWidget : QStackedWidget com fade + slide ao trocar de pagina
    - RippleOverlay : efeito ripple ao clicar em um QPushButton
    - install_hover_glow : sombra suave animada ao passar o mouse
    - install_click_pulse : leve animacao de "pressionar" ao clicar
    - pulse_border : pulsa a borda de um QFrame (ex.: DropZone)
    - fade_in : anima a entrada de um widget (opacidade + subida)
"""
from __future__ import annotations

import math
import random
from typing import Optional

from PySide6.QtCore import (
    Qt, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QTimer,
    QPropertyAnimation, QEasingCurve, QParallelAnimationGroup,
    QSequentialAnimationGroup, QAbstractAnimation, Property, Signal,
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QLinearGradient, QRadialGradient,
    QPen, QBrush, QPaintEvent, QMouseEvent,
)
from PySide6.QtWidgets import (
    QWidget, QStackedWidget, QGraphicsOpacityEffect,
    QGraphicsDropShadowEffect, QPushButton, QFrame,
)


# =============================================================
# Animated background - "aurora" de orbes pulsando ao fundo
# =============================================================
class AnimatedBackground(QWidget):
    """Widget decorativo com gradiente + orbes de luz que flutuam suavemente.

    Deve ficar atras do conteudo. Use como widget de fundo de uma pagina
    ou dentro de um stack, com children desenhando por cima.
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 base: str = "#1C1B1A",
                 accent: str = "#D97757",
                 accent2: str = "#5E8CC7",
                 n_orbs: int = 5,
                 fps: int = 30):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._base = QColor(base)
        self._accent = QColor(accent)
        self._accent2 = QColor(accent2)
        self._phase = 0.0
        random.seed(7)
        self._orbs = []
        for _ in range(n_orbs):
            self._orbs.append({
                "x": random.random(),
                "y": random.random(),
                "r": random.uniform(0.18, 0.35),   # raio relativo
                "speed": random.uniform(0.002, 0.006),
                "dir": random.uniform(0, 2 * math.pi),
                "color": self._accent if random.random() < 0.6 else self._accent2,
                "alpha": random.randint(18, 42),
            })
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._phase += 0.01
        for o in self._orbs:
            o["x"] += math.cos(o["dir"]) * o["speed"]
            o["y"] += math.sin(o["dir"]) * o["speed"]
            # rebater suavemente nas bordas
            if o["x"] < -0.1 or o["x"] > 1.1:
                o["dir"] = math.pi - o["dir"]
            if o["y"] < -0.1 or o["y"] > 1.1:
                o["dir"] = -o["dir"]
        self.update()

    def paintEvent(self, e: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        # gradiente base diagonal sutil
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, self._base)
        darker = QColor(self._base)
        darker = darker.darker(110)
        grad.setColorAt(1.0, darker)
        p.fillRect(rect, grad)

        w, h = rect.width(), rect.height()
        # orbes com radial gradient
        for o in self._orbs:
            cx = o["x"] * w
            cy = o["y"] * h
            r = o["r"] * max(w, h)
            rg = QRadialGradient(QPointF(cx, cy), r)
            c = QColor(o["color"])
            c.setAlpha(o["alpha"])
            rg.setColorAt(0.0, c)
            edge = QColor(o["color"])
            edge.setAlpha(0)
            rg.setColorAt(1.0, edge)
            p.setBrush(QBrush(rg))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), r, r)
        p.end()


# =============================================================
# Stacked widget com transicao suave
# =============================================================
class AnimatedStackedWidget(QStackedWidget):
    """QStackedWidget que faz um fade crossfade ao trocar de pagina.

    Chame setCurrentIndex/setCurrentWidget normalmente.
    """

    def __init__(self, parent: Optional[QWidget] = None, duration: int = 220):
        super().__init__(parent)
        self._duration = duration
        self._anim: Optional[QParallelAnimationGroup] = None
        self._fx_in: Optional[QGraphicsOpacityEffect] = None
        self._fx_out: Optional[QGraphicsOpacityEffect] = None

    def setCurrentIndex(self, index: int):
        old = self.currentIndex()
        if index == old:
            return super().setCurrentIndex(index)
        self._animate(old, index)

    def setCurrentWidget(self, w: QWidget):
        self.setCurrentIndex(self.indexOf(w))

    def _animate(self, old_idx: int, new_idx: int):
        old_w = self.widget(old_idx)
        new_w = self.widget(new_idx)
        if old_w is None or new_w is None:
            return super().setCurrentIndex(new_idx)

        # Fade in do novo, aplicando um opacity effect
        self._fx_in = QGraphicsOpacityEffect(new_w)
        self._fx_in.setOpacity(0.0)
        new_w.setGraphicsEffect(self._fx_in)
        super().setCurrentIndex(new_idx)

        anim_in = QPropertyAnimation(self._fx_in, b"opacity", self)
        anim_in.setDuration(self._duration)
        anim_in.setStartValue(0.0)
        anim_in.setEndValue(1.0)
        anim_in.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_in)

        def _cleanup():
            try:
                new_w.setGraphicsEffect(None)
            except RuntimeError:
                pass

        group.finished.connect(_cleanup)
        self._anim = group
        group.start(QAbstractAnimation.DeleteWhenStopped)


# =============================================================
# Ripple overlay para QPushButton
# =============================================================
class RippleOverlay(QWidget):
    """Desenha um ripple se expandindo quando o botao e clicado.

    Instalado automaticamente por install_ripple().
    """

    def __init__(self, parent: QWidget, color: str = "#D97757"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._color = QColor(color)
        self._radius = 0.0
        self._center = QPointF(0, 0)
        self._max_r = 0.0
        self._opacity = 0.0
        self._anim: Optional[QParallelAnimationGroup] = None
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self.parent():
            if ev.type() == QEvent.Resize:
                self.setGeometry(self.parent().rect())
            elif ev.type() == QEvent.MouseButtonPress and isinstance(ev, QMouseEvent):
                if ev.button() == Qt.LeftButton:
                    self._start_ripple(ev.position().toPoint())
        return False

    def _start_ripple(self, pos: QPoint):
        self._center = QPointF(pos)
        r = self.rect()
        # raio maximo = distancia do clique ao canto mais longe
        corners = [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]
        self._max_r = max(math.hypot(pos.x() - c.x(), pos.y() - c.y()) for c in corners)
        self.show()
        self.raise_()

        anim_r = QPropertyAnimation(self, b"radius", self)
        anim_r.setDuration(420)
        anim_r.setStartValue(0.0)
        anim_r.setEndValue(float(self._max_r))
        anim_r.setEasingCurve(QEasingCurve.OutCubic)

        anim_o = QPropertyAnimation(self, b"rippleOpacity", self)
        anim_o.setDuration(420)
        anim_o.setStartValue(0.45)
        anim_o.setEndValue(0.0)
        anim_o.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_r)
        group.addAnimation(anim_o)
        group.finished.connect(self.hide)
        self._anim = group
        group.start(QAbstractAnimation.DeleteWhenStopped)

    # Propriedades animaveis
    def _get_radius(self) -> float: return self._radius
    def _set_radius(self, v: float):
        self._radius = v
        self.update()
    radius = Property(float, _get_radius, _set_radius)

    def _get_opacity(self) -> float: return self._opacity
    def _set_opacity(self, v: float):
        self._opacity = v
        self.update()
    rippleOpacity = Property(float, _get_opacity, _set_opacity)

    def paintEvent(self, e: QPaintEvent):
        if self._radius <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QColor(self._color)
        c.setAlphaF(max(0.0, min(1.0, self._opacity)))
        p.setBrush(QBrush(c))
        p.setPen(Qt.NoPen)
        # recorta dentro do botao
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 7, 7)
        p.setClipPath(path)
        p.drawEllipse(self._center, self._radius, self._radius)
        p.end()


def install_ripple(button: QPushButton, color: str = "#D97757") -> RippleOverlay:
    """Instala efeito ripple num QPushButton."""
    overlay = RippleOverlay(button, color=color)
    overlay.setGeometry(button.rect())
    return overlay


# =============================================================
# Glow suave no hover
# =============================================================
class _HoverGlowFilter(QObject):
    def __init__(self, widget: QWidget, color: str, blur: int, parent=None):
        super().__init__(parent or widget)
        self._w = widget
        self._effect = QGraphicsDropShadowEffect(widget)
        self._effect.setBlurRadius(0)
        self._effect.setOffset(0, 0)
        self._effect.setColor(QColor(color))
        # Aplica direto no proprio widget (nunca no pai).
        # Aplicar no pai causava conflito quando multiplos botoes da sidebar
        # registravam efeitos no mesmo QFrame pai, corrompendo o layout.
        widget.setGraphicsEffect(self._effect)
        self._target_blur = blur
        self._anim = QPropertyAnimation(self._effect, b"blurRadius", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self._w:
            if ev.type() == QEvent.Enter:
                self._anim.stop()
                self._anim.setStartValue(self._effect.blurRadius())
                self._anim.setEndValue(self._target_blur)
                self._anim.start()
            elif ev.type() == QEvent.Leave:
                self._anim.stop()
                self._anim.setStartValue(self._effect.blurRadius())
                self._anim.setEndValue(0)
                self._anim.start()
        return False


def install_hover_glow(widget: QWidget, color: str = "#D97757", blur: int = 28):
    """Adiciona uma sombra/glow animado quando o mouse entra no widget.

    O efeito e aplicado diretamente no proprio widget. Antes era aplicado no
    pai, o que causava conflito quando varios botoes do mesmo pai registravam
    efeitos — o Qt descartava todos menos um, corrompendo o layout da sidebar.
    """
    return _HoverGlowFilter(widget, color, blur)


# =============================================================
# Pulse na borda (para DropZone ativo, por exemplo)
# =============================================================
class BorderPulse(QObject):
    """Alterna a opacidade/glow de uma borda usando um efeito de sombra."""

    def __init__(self, widget: QWidget, color: str = "#D97757", parent=None):
        super().__init__(parent or widget)
        self._fx = QGraphicsDropShadowEffect(widget)
        self._fx.setOffset(0, 0)
        self._fx.setColor(QColor(color))
        self._fx.setBlurRadius(0)
        widget.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"blurRadius", self)
        self._anim.setDuration(900)
        self._anim.setLoopCount(-1)
        self._anim.setKeyValueAt(0.0, 4)
        self._anim.setKeyValueAt(0.5, 32)
        self._anim.setKeyValueAt(1.0, 4)
        self._anim.setEasingCurve(QEasingCurve.InOutSine)

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self._fx.setBlurRadius(0)


# =============================================================
# Fade-in de entrada com leve subida
# =============================================================
def fade_in(widget: QWidget, duration: int = 260, y_offset: int = 10):
    """Anima a entrada de um widget (opacidade 0->1 + leve subida)."""
    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(0.0)
    widget.setGraphicsEffect(fx)

    anim_op = QPropertyAnimation(fx, b"opacity", widget)
    anim_op.setDuration(duration)
    anim_op.setStartValue(0.0)
    anim_op.setEndValue(1.0)
    anim_op.setEasingCurve(QEasingCurve.OutCubic)

    geo = widget.geometry()
    shifted = QRect(geo.x(), geo.y() + y_offset, geo.width(), geo.height())
    widget.setGeometry(shifted)
    anim_pos = QPropertyAnimation(widget, b"geometry", widget)
    anim_pos.setDuration(duration)
    anim_pos.setStartValue(shifted)
    anim_pos.setEndValue(geo)
    anim_pos.setEasingCurve(QEasingCurve.OutCubic)

    group = QParallelAnimationGroup(widget)
    group.addAnimation(anim_op)
    group.addAnimation(anim_pos)

    def _cleanup():
        try:
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass

    group.finished.connect(_cleanup)
    group.start(QAbstractAnimation.DeleteWhenStopped)
    return group
