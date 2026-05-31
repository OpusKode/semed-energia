"""
Gera o arquivo icon.ico no padrao Microsoft (multi-resolucao) a partir do
icon.png.

O formato .ico do Windows embala varias resolucoes no mesmo arquivo; o
sistema escolhe a mais adequada conforme o contexto (taskbar, Alt-Tab,
explorador, atalhos na area de trabalho, etc.).

Sizes seguem as diretrizes da Microsoft:
    16, 20, 24, 32, 40, 48, 64, 96, 128, 256

Uso:
    python ui/assets/build_icon.py
"""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit(
        "Pillow nao esta instalado. Rode:\n"
        "    pip install pillow"
    )


AQUI = Path(__file__).parent
PNG = AQUI / "icon.png"
ICO = AQUI / "icon.ico"

TAMANHOS = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
            (48, 48), (64, 64), (96, 96), (128, 128), (256, 256)]


def main():
    if not PNG.exists():
        sys.exit(
            f"Arquivo nao encontrado: {PNG}\n"
            f"Salve a imagem do sistema como icon.png nesta pasta antes "
            f"de rodar este script."
        )

    img = Image.open(PNG).convert("RGBA")

    # Garantir que e quadrada (senao o Windows distorce)
    if img.width != img.height:
        lado = max(img.width, img.height)
        fundo = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
        off_x = (lado - img.width) // 2
        off_y = (lado - img.height) // 2
        fundo.paste(img, (off_x, off_y))
        img = fundo

    # Para cada tamanho, resample com qualidade alta (LANCZOS).
    # Pillow cuida de empacotar tudo no .ico quando passamos `sizes=`.
    img.save(ICO, format="ICO", sizes=TAMANHOS)
    print(f"Gerado {ICO}")
    print(f"Tamanhos embutidos: {', '.join(f'{w}x{h}' for w, h in TAMANHOS)}")


if __name__ == "__main__":
    main()
