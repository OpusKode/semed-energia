"""
Exportacao bruta (raw) das tabelas do banco.

Gera:
    * um diretorio com um CSV por tabela, OU
    * um unico .xlsx "bruto" com uma aba por tabela.

Diferente de `export.powerbi` (que usa views desnormalizadas / modelo estrela),
aqui o objetivo eh oferecer uma copia crua do banco — util para backup,
auditoria e analises ad-hoc que nao se encaixem no modelo Power BI.

API publica:
    exportar_csv(destino_dir, session, tabelas=None, on_progress=None) -> dict
    exportar_xlsx_raw(destino_xlsx, session, tabelas=None, on_progress=None) -> dict
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session


# Tabelas exportadas por padrao. A ordem aqui eh cosmetica (nome das abas/arquivos).
TABELAS_RAW = [
    "fatura_agrupadora",
    "fatura_individual",
    "tributo",
    "valor_faturado",
    "valor_medido",
    "arquivo_processado",
]


# =============================================================
# Helpers
# =============================================================

def _existe_tabela(session: Session, nome: str) -> bool:
    """True se a tabela existe. Funciona em SQLite e PostgreSQL."""
    if session.get_bind().dialect.name == "sqlite":
        q = text(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name=:n LIMIT 1"
        )
    else:
        q = text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n LIMIT 1"
        )
    return session.execute(q, {"n": nome}).first() is not None


def _norm_csv(v):
    """Normaliza valores Python para CSV (strings simples)."""
    if v is None:
        return ""
    if isinstance(v, Decimal):
        # Preserva precisao usando str(), nao float().
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _norm_xlsx(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def _resolver_tabelas(session: Session, tabelas: list[str] | None) -> list[str]:
    alvo = tabelas or TABELAS_RAW
    existentes = [t for t in alvo if _existe_tabela(session, t)]
    return existentes


# =============================================================
# Exportacao CSV
# =============================================================

def exportar_csv(
    destino_dir: str | Path,
    session: Session,
    tabelas: list[str] | None = None,
    on_progress=None,
) -> dict:
    """
    Exporta cada tabela para um CSV no diretorio `destino_dir`.

    Retorna estatisticas: {arquivos: int, linhas: int, ignoradas: [str], destino: str}.
    """
    destino = Path(destino_dir)
    destino.mkdir(parents=True, exist_ok=True)

    alvo = tabelas or TABELAS_RAW
    ignoradas = [t for t in alvo if not _existe_tabela(session, t)]
    existentes = _resolver_tabelas(session, alvo)

    linhas_total = 0
    arquivos = 0

    for i, tabela in enumerate(existentes):
        if on_progress:
            on_progress(i, len(existentes), tabela)

        result = session.execute(text(f"SELECT * FROM {tabela}"))
        colunas = list(result.keys())
        caminho = destino / f"{tabela}.csv"

        with caminho.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            w.writerow(colunas)
            n = 0
            for row in result:
                w.writerow(_norm_csv(v) for v in row)
                n += 1

        arquivos += 1
        linhas_total += n

    if on_progress:
        on_progress(len(existentes), len(existentes), "concluido")

    return {
        "arquivos": arquivos,
        "linhas": linhas_total,
        "ignoradas": ignoradas,
        "destino": str(destino),
    }


# =============================================================
# Exportacao XLSX bruto
# =============================================================

def exportar_xlsx_raw(
    destino_xlsx: str | Path,
    session: Session,
    tabelas: list[str] | None = None,
    on_progress=None,
) -> dict:
    """
    Exporta as tabelas para um unico arquivo .xlsx (uma aba por tabela).

    Retorna: {sheets: int, linhas: int, ignoradas: [str], caminho: str}.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    destino = Path(destino_xlsx)

    alvo = tabelas or TABELAS_RAW
    ignoradas = [t for t in alvo if not _existe_tabela(session, t)]
    existentes = _resolver_tabelas(session, alvo)

    wb = Workbook()
    wb.remove(wb.active)

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="5B5750")  # cinza-terra
    header_align = Alignment(horizontal="left", vertical="center")

    linhas_total = 0
    sheets_ok = 0

    for i, tabela in enumerate(existentes):
        if on_progress:
            on_progress(i, len(existentes), tabela)

        result = session.execute(text(f"SELECT * FROM {tabela}"))
        colunas = list(result.keys())
        if not colunas:
            ignoradas.append(tabela)
            continue

        ws = wb.create_sheet(tabela[:31])  # nome da aba limitado pelo Excel

        for c, col in enumerate(colunas, 1):
            cell = ws.cell(1, c, col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        n = 0
        max_len = [len(str(c)) for c in colunas]
        for row in result:
            for c, v in enumerate(row, 1):
                ws.cell(n + 2, c, _norm_xlsx(v))
                if n < 50:
                    s = "" if v is None else str(v)
                    if len(s) > max_len[c - 1]:
                        max_len[c - 1] = len(s)
            n += 1

        for c, tam in enumerate(max_len, 1):
            ws.column_dimensions[get_column_letter(c)].width = min(max(tam + 2, 10), 60)

        ws.freeze_panes = "A2"
        linhas_total += n
        sheets_ok += 1

    # Aba de metadados
    meta = wb.create_sheet("_Metadados", 0)
    meta["A1"] = "SEMED Energia — Export bruto"
    meta["A1"].font = Font(bold=True, size=14, color="D97757")
    meta["A3"] = "Gerado em"
    meta["B3"] = datetime.now()
    meta["B3"].number_format = "dd/mm/yyyy hh:mm"
    meta["A4"] = "Total de abas"
    meta["B4"] = sheets_ok
    meta["A5"] = "Total de linhas"
    meta["B5"] = linhas_total
    meta["A6"] = "Tabelas ausentes"
    meta["B6"] = ", ".join(ignoradas) if ignoradas else "nenhuma"
    meta.column_dimensions["A"].width = 28
    meta.column_dimensions["B"].width = 60

    wb.save(destino)

    if on_progress:
        on_progress(len(existentes), len(existentes), "concluido")

    return {
        "sheets": sheets_ok,
        "linhas": linhas_total,
        "ignoradas": ignoradas,
        "caminho": str(destino),
    }
