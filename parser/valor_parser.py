"""
Conversão de valores no formato brasileiro para Decimal.

Formatos tratados:
    '153.489,82'  → Decimal('153489.82')   (monetário com milhar)
    '1.258120'    → Decimal('1.258120')    (preço unitário sem vírgula)
    '1,258120'    → Decimal('1.258120')    (preço unitário com vírgula)
    '19,0000'     → Decimal('19.0000')     (alíquota)
    '7,28'        → Decimal('7.28')        (valor pequeno)
    '0,00'        → Decimal('0.00')
    '2.800,45-'   → Decimal('-2800.45')    (valor negativo)
    '2.800,45'    → Decimal('2800.45')
"""
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from datetime import date


def normalizar_texto(texto: str) -> str:
    """Normaliza Unicode (composto vs decomposto) de diferentes geradores PDF."""
    return unicodedata.normalize("NFC", texto)


def parse_valor_br(texto: str) -> Decimal | None:
    """
    Converte valor no formato brasileiro para Decimal.

    Regra de decisão:
    - Se tem vírgula → formato BR (ponto=milhar, vírgula=decimal)
    - Se não tem vírgula → formato numérico direto (ponto=decimal)
    - Se termina em '-' → valor negativo
    """
    if not texto:
        return None

    texto = texto.strip()
    if not texto:
        return None

    # Detectar sinal negativo (trailing '-')
    negativo = texto.endswith("-")
    if negativo:
        texto = texto[:-1].strip()

    # Remover 'R$' se presente
    texto = texto.replace("R$", "").strip()

    # Remover espaços internos
    texto = texto.replace(" ", "")

    if not texto:
        return None

    try:
        if "," in texto:
            # Formato brasileiro: ponto=milhar, vírgula=decimal
            valor = Decimal(texto.replace(".", "").replace(",", "."))
        else:
            # Formato numérico direto
            valor = Decimal(texto)

        return -valor if negativo else valor
    except Exception:
        return None


def parse_quantidade(texto: str) -> Decimal | None:
    """
    Converte quantidade (kWh, kW).
    Quantidades usam ponto decimal sem separador de milhar.
    Ex: '156895.19', '1224.92', '166.42'
    """
    if not texto:
        return None
    texto = texto.strip()
    # Se tem vírgula, é formato BR (ponto=milhar, vírgula=decimal)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except Exception:
        return None


def parse_data_br(texto: str) -> date | None:
    """
    Converte data no formato brasileiro para date.
    '31.01.2026' → date(2026, 1, 31)
    '31/01/2026' → date(2026, 1, 31)
    '20-02-2026' → date(2026, 2, 20)
    """
    if not texto:
        return None
    texto = texto.strip()
    # Normalizar separadores
    texto = texto.replace(".", "/").replace("-", "/")
    try:
        partes = texto.split("/")
        if len(partes) == 3:
            dia, mes, ano = int(partes[0]), int(partes[1]), int(partes[2])
            return date(ano, mes, dia)
    except (ValueError, IndexError):
        pass
    return None


def parse_int_safe(texto: str) -> int | None:
    """Converte texto para inteiro de forma segura."""
    if not texto:
        return None
    try:
        return int(texto.strip())
    except ValueError:
        return None
