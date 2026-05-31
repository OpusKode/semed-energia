"""
Configuração centralizada de logging.
Gera logs no console e em arquivo rotativo.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from config import PASTA_LOGS, LOG_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT


def configurar_logging() -> logging.Logger:
    """
    Configura o logger principal do sistema.
    - Console: nível configurável (default INFO)
    - Arquivo: log diário em logs/semed_YYYY-MM-DD.log
    """
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("semed")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Evitar duplicar handlers se chamado mais de uma vez
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Handler: Console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler: Arquivo diário
    hoje = datetime.now().strftime("%Y-%m-%d")
    arquivo_log = PASTA_LOGS / f"semed_{hoje}.log"
    file_handler = logging.FileHandler(arquivo_log, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
