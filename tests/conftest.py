"""
Configuração comum dos testes.

- Adiciona a raiz do projeto no sys.path (mesmo truque do main.py).
- Define a CLI option `--update-golden` usada pelo smoke test.
"""
import sys
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Reescreve os arquivos em tests/golden/ com os resultados atuais.",
    )


# Mesma manipulação de sys.path do main.py — permite `import parser`, `import db`, etc.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
