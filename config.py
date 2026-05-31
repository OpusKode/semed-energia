"""
Configuracoes centralizadas do sistema SEMED Energia.

Resolve automaticamente:
  - APP_DIR  : pasta do codigo/recursos (read-only quando instalado).
  - DATA_DIR : pasta de dados do usuario (gravavel, sobrevive a updates).
  - Banco    : SQLite local (arquivo unico, sem servidor) por padrao.

Tudo pode ser sobrescrito via variaveis de ambiente:
  SEMED_DATA_DIR, SEMED_DB_PATH, SEMED_DB_URL, SEMED_LOG_LEVEL.
"""
from pathlib import Path
from decimal import Decimal
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _is_frozen() -> bool:
    """True quando rodando como executavel empacotado (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


# --- Caminhos ----------------------------------------------------------
# APP_DIR: onde esta o codigo/recursos.
#   - Dev: a pasta deste arquivo.
#   - Instalado: a pasta do executavel.
if _is_frozen():
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

# BASE_DIR mantido por compatibilidade com imports legados.
BASE_DIR = APP_DIR


def _resolver_data_dir() -> Path:
    """
    Pasta de dados do usuario (gravavel e preservada entre atualizacoes).

    Prioridade:
      1. SEMED_DATA_DIR (override explicito).
      2. Instalado  -> %LOCALAPPDATA%/SEMED Energia.
      3. Desenvolvimento -> raiz do projeto (comportamento historico).
    """
    override = os.getenv("SEMED_DATA_DIR")
    if override:
        return Path(override)
    if _is_frozen():
        base = os.getenv("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "SEMED Energia"
    return APP_DIR


DATA_DIR = _resolver_data_dir()

PASTA_ENTRADA = DATA_DIR / "entrada"
PASTA_PROCESSADOS = DATA_DIR / "processados"
PASTA_DUPLICADOS = DATA_DIR / "duplicados"
PASTA_ERROS = DATA_DIR / "erros"
PASTA_LOGS = DATA_DIR / "logs"

TODAS_AS_PASTAS = [PASTA_ENTRADA, PASTA_PROCESSADOS, PASTA_DUPLICADOS, PASTA_ERROS, PASTA_LOGS]


def garantir_pastas() -> None:
    """Cria todas as pastas de dados se ainda nao existirem."""
    for p in TODAS_AS_PASTAS:
        p.mkdir(parents=True, exist_ok=True)


# --- Banco de Dados (SQLite) ------------------------------------------
# Arquivo unico dentro de DATA_DIR. Sem servidor, sem instalacao.
DB_PATH = Path(os.getenv("SEMED_DB_PATH", str(DATA_DIR / "semed_energia.db")))
# Permite override total (ex.: apontar para um Postgres em dev).
DB_URL = os.getenv("SEMED_DB_URL", f"sqlite:///{DB_PATH.as_posix()}")

# --- Validacao --------------------------------------------------------
TOLERANCIA_ITEM = Decimal("0.02")     # R$ 0,02 por item individual
TOLERANCIA_TOTAL = Decimal("0.05")    # R$ 0,05 para total da agrupadora
ALIQUOTA_ICMS_PA = Decimal("19.00")   # Aliquota padrao do Para

# --- Parsing ----------------------------------------------------------
CONCESSIONARIA_ESPERADA = "EQUATORIAL PARÁ"

# --- Logging ----------------------------------------------------------
LOG_LEVEL = os.getenv("SEMED_LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
