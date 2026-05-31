"""
Gera os ícones do app a partir do vetor `icon.svg` (fonte de verdade):

    icon.svg  --(QtSvg)-->  icon.png (1024x1024)  --(Pillow)-->  icon.ico (multi-res)

O .ico do Windows embala várias resoluções no mesmo arquivo; o sistema escolhe
a mais adequada conforme o contexto (taskbar, Alt-Tab, explorador, atalhos...).

Se `icon.svg` não existir, reaproveita o `icon.png` que já estiver na pasta
(modo legado). Rode após trocar o logo:

    python ui/assets/build_icon.py
"""
import os
import sys
from pathlib import Path

AQUI = Path(__file__).parent
SVG = AQUI / "icon.svg"
PNG = AQUI / "icon.png"
ICO = AQUI / "icon.ico"

# Lado do PNG mestre. 1024 dá folga para todas as resoluções do .ico e para a
# logo da sidebar (escalada para 96 px com suavização).
PNG_LADO = 1024

# Tamanhos embutidos no .ico (diretrizes da Microsoft).
TAMANHOS = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
            (48, 48), (64, 64), (96, 96), (128, 128), (256, 256)]


def _render_png_do_svg() -> None:
    """Rasteriza icon.svg -> icon.png usando o QtSvg (PySide6)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    _ = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise RuntimeError(f"SVG inválido para o QtSvg: {SVG}")

    img = QImage(PNG_LADO, PNG_LADO, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()

    if not img.save(str(PNG), "PNG"):
        raise RuntimeError(f"Falha ao salvar {PNG}")
    print(f"PNG renderizado do SVG: {PNG} ({PNG_LADO}x{PNG_LADO})")


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow não está instalado. Rode:  pip install pillow")

    if SVG.exists():
        try:
            _render_png_do_svg()
        except Exception as e:
            print(f"⚠ Não foi possível renderizar do SVG ({e}); "
                  f"usando o icon.png existente.")

    if not PNG.exists():
        sys.exit(f"Arquivo não encontrado: {PNG}\n"
                 f"Salve a logo como icon.svg (ou icon.png) nesta pasta.")

    img = Image.open(PNG).convert("RGBA")

    # Garantir que é quadrada (senão o Windows distorce).
    if img.width != img.height:
        lado = max(img.width, img.height)
        fundo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        fundo.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2))
        img = fundo

    img.save(ICO, format="ICO", sizes=TAMANHOS)
    print(f"Gerado {ICO}")
    print(f"Tamanhos embutidos: {', '.join(f'{w}x{h}' for w, h in TAMANHOS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
