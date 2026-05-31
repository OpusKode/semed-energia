"""
Exportacao de dados para Power BI.

Gera um arquivo Excel (.xlsx) com uma aba por view desnormalizada,
pronta para ser importada em "Obter Dados" > "Excel" no Power BI Desktop.

As views usadas ja estao desenhadas para serem modelo-estrela-friendly:

    FatoConsumo         — fato principal, 1 linha por fatura individual
    ResumoMensal        — agregado por mes/referencia
    RankingUnidades     — unidades ordenadas por consumo
    Leituras            — leituras medidas por fatura
    TributosDetalhado   — ICMS/COFINS/PIS por fatura
    ControleImportacao  — arquivos processados
    DimCalendario       — dimensao tempo (365+ dias)

Se alguma view nao existir no banco, ela e pulada com warning.
"""
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


# =============================================================
# Configuracao
# =============================================================

# Ordem importa: fato primeiro, depois dimensoes/agregados
VIEWS_POWER_BI = [
    ("FatoConsumo",         "vw_fato_consumo"),
    ("ResumoMensal",        "vw_resumo_mensal"),
    ("RankingUnidades",     "vw_ranking_unidades"),
    ("Leituras",            "vw_leituras"),
    ("TributosDetalhado",   "vw_tributos_detalhado"),
    ("ControleImportacao",  "vw_controle_importacao"),
    ("DimCalendario",       "vw_dim_calendario"),
]

# Fallback: se views nao existem, exporta tabelas diretamente.
TABELAS_FALLBACK = [
    ("Agrupadoras",       "fatura_agrupadora"),
    ("FaturasIndividuais", "fatura_individual"),
    ("Tributos",          "tributo"),
    ("ValoresFaturados",  "valor_faturado"),
    ("ValoresMedidos",    "valor_medido"),
    ("Arquivos",          "arquivo_processado"),
]


# =============================================================
# Helpers
# =============================================================

def _existe_relacao(session: Session, nome: str) -> bool:
    """True se a relacao (view ou tabela) existe. Funciona em SQLite e PostgreSQL."""
    if session.get_bind().dialect.name == "sqlite":
        q = text("""
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table', 'view') AND name = :n
            LIMIT 1
        """)
    else:
        q = text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :n
            UNION ALL
            SELECT 1 FROM information_schema.views
            WHERE table_schema = 'public' AND table_name = :n
            LIMIT 1
        """)
    return session.execute(q, {"n": nome}).first() is not None


def _norm_valor(v):
    """Normaliza valores Python para openpyxl."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v
    return v


def _largura_coluna(valores: list) -> int:
    """Estima largura apropriada para uma coluna baseada nos valores."""
    max_len = 0
    for v in valores:
        if v is None:
            continue
        tam = len(str(v))
        if tam > max_len:
            max_len = tam
    return min(max(max_len + 2, 10), 50)  # entre 10 e 50


# =============================================================
# API publica
# =============================================================

def exportar_para_excel(
    caminho: str | Path,
    session: Session,
    on_progress=None,
) -> dict:
    """
    Gera arquivo .xlsx com uma sheet por view/tabela.

    :param caminho: destino do .xlsx
    :param session: SQLAlchemy Session conectada
    :param on_progress: callable(i, total, nome) para reporte de progresso
    :return: dict com estatisticas {sheets: int, linhas: int, ignoradas: [str]}
    """
    caminho = Path(caminho)
    wb = Workbook()
    wb.remove(wb.active)

    # Decide se usa views ou tabelas
    fontes = VIEWS_POWER_BI.copy()
    if not _existe_relacao(session, VIEWS_POWER_BI[0][1]):
        # Nao ha views — cai pra tabelas
        fontes = TABELAS_FALLBACK.copy()

    ignoradas = []
    sheets_ok = 0
    linhas_total = 0

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="D97757")  # laranja Anthropic
    header_align = Alignment(horizontal="left", vertical="center")

    for i, (nome_sheet, nome_relacao) in enumerate(fontes):
        if on_progress:
            on_progress(i, len(fontes), nome_sheet)

        if not _existe_relacao(session, nome_relacao):
            ignoradas.append(nome_relacao)
            continue

        result = session.execute(text(f"SELECT * FROM {nome_relacao}"))
        colunas = list(result.keys())
        if not colunas:
            ignoradas.append(nome_relacao)
            continue

        ws = wb.create_sheet(nome_sheet)

        # Cabecalho
        for c, col in enumerate(colunas, 1):
            cell = ws.cell(1, c, col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        # Dados
        n = 0
        amostras_por_col = [[] for _ in colunas]
        for row in result:
            for c, v in enumerate(row, 1):
                ws.cell(n + 2, c, _norm_valor(v))
                if n < 25:
                    amostras_por_col[c - 1].append(v)
            n += 1
        linhas_total += n

        # Largura das colunas (baseada nas 25 primeiras amostras)
        for c, amostras in enumerate(amostras_por_col, 1):
            ws.column_dimensions[get_column_letter(c)].width = _largura_coluna(
                amostras + [colunas[c - 1]]
            )

        # Freeze header
        ws.freeze_panes = "A2"

        # Transformar em Tabela nomeada (Power BI identifica auto)
        if n > 0:
            last_col = get_column_letter(len(colunas))
            ref = f"A1:{last_col}{n + 1}"
            # Nome da tabela nao pode conter espaco
            tbl = Table(displayName=nome_sheet, ref=ref)
            tbl.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showRowStripes=True,
            )
            ws.add_table(tbl)

        sheets_ok += 1

    # Aba de metadados
    meta = wb.create_sheet("_Metadados", 0)
    meta["A1"] = "SEMED Energia — Exportação Power BI"
    meta["A1"].font = Font(bold=True, size=14, color="D97757")
    meta["A3"] = "Gerado em"
    meta["B3"] = datetime.now()
    meta["B3"].number_format = "dd/mm/yyyy hh:mm"
    meta["A4"] = "Total de sheets"
    meta["B4"] = sheets_ok
    meta["A5"] = "Total de linhas"
    meta["B5"] = linhas_total
    meta["A6"] = "Views/tabelas ignoradas"
    meta["B6"] = ", ".join(ignoradas) if ignoradas else "nenhuma"
    meta.column_dimensions["A"].width = 28
    meta.column_dimensions["B"].width = 60

    wb.save(caminho)

    return {
        "sheets": sheets_ok,
        "linhas": linhas_total,
        "ignoradas": ignoradas,
        "caminho": str(caminho),
    }
