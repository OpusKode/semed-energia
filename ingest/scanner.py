"""
Scanner de pastas de mês.

Recebe uma pasta de mês (ex.: `2020/10-OUTUBRO-2020/`) e devolve uma lista
de `LoteAgrupadora` — um por agrupadora detectada. Dois modos:

1. Subpastas por agrupadora  : cada subpasta = 1 lote (padrão 2020-2022).
2. PDFs planos no nível mês  : agrupados por complemento extraído do nome
   ou do conteúdo do PDF (padrão 2023-2026).
"""
import logging
import re
from pathlib import Path

import fitz  # PyMuPDF

from ingest.detector_formato import detectar_formato
from ingest.tipos import ArquivoIngest, LoteAgrupadora

log = logging.getLogger("semed.ingest.scanner")

# ─── Meses pt-BR ─────────────────────────────────────────────
_MESES: dict[str, int] = {
    "JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3,
    "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7,
    "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10,
    "NOVEMBRO": 11, "DEZEMBRO": 12,
}

_RE_ANO = re.compile(r"\b(20\d{2})\b")
_RE_MES_NUM = re.compile(r"^(\d{1,2})")

# Romanos: ordenados do mais longo ao mais curto para o search funcionar bem.
_ROMANO: dict[str, str] = {
    "IV": "IV", "III": "III", "II": "II", "I": "I",
    "4": "IV", "3": "III", "2": "II", "1": "I",
}
_RE_ROMANO = re.compile(r"\b(IV|III|II|I|[1-4])\b")

# Subpastas que não são agrupadoras (comprovantes, "novas", etc.)
_RE_EXCLUIR_SUB = re.compile(
    r"comprovante|compro|pagamento|novas|fatura\s+errada", re.IGNORECASE
)


# ─── Utilitários ─────────────────────────────────────────────

def listar_pdfs(pasta: Path) -> list[Path]:
    """PDFs diretos numa pasta (case-insensitive, sem duplicatas)."""
    vistos: dict[str, Path] = {}
    for p in pasta.iterdir():
        if p.is_file() and p.suffix.lower() == ".pdf":
            vistos.setdefault(p.name.lower(), p)
    return sorted(vistos.values(), key=lambda p: p.name.lower())


def _extrair_ano_mes(pasta_mes: Path) -> tuple[int, int]:
    """Extrai (ano, mes) a partir da hierarquia de nomes de pasta."""
    # Ano: primeiro 20XX encontrado percorrendo da raiz para a folha.
    ano = 0
    for parte in pasta_mes.parts:
        m = _RE_ANO.search(parte)
        if m:
            ano = int(m.group(1))
            break

    # Mês: dígito inicial no nome da pasta, ou nome do mês.
    nome = pasta_mes.name.upper()
    m = _RE_MES_NUM.match(nome)
    if m:
        mes = int(m.group(1))
    else:
        mes = next((v for n, v in _MESES.items() if n in nome), 0)

    return ano, mes


def _normalizar_complemento(texto: str) -> str:
    """SEMED-I | SEMED-II | SEMED-III | SEMED-IV | ? """
    texto_up = texto.upper()
    if "SEMED" not in texto_up:
        return "?"
    m = _RE_ROMANO.search(texto_up)
    if not m:
        return "?"
    return "SEMED-" + _ROMANO[m.group(1)]


def _complemento_pdf(caminho: Path) -> str:
    """Complemento extraído do conteúdo da primeira página do PDF."""
    try:
        doc = fitz.open(str(caminho))
        try:
            texto = doc[0].get_text()
        finally:
            doc.close()
        return _normalizar_complemento(texto)
    except Exception:
        return "?"


def _complemento_grupo(nome: str, pdfs: list[Path]) -> str:
    """Tenta extrair complemento do nome; se "?", lê o conteúdo do PDF."""
    comp = _normalizar_complemento(nome)
    if comp == "?" and pdfs:
        comp = _complemento_pdf(pdfs[0])
    return comp


# ─── Grupos de agrupadora ────────────────────────────────────

def _subpastas_agrupadora(pasta_mes: Path) -> list[Path]:
    """Subpastas que parecem ser de uma agrupadora (têm PDFs, não são comprovantes)."""
    resultado = []
    for d in sorted(pasta_mes.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir():
            continue
        if _RE_EXCLUIR_SUB.search(d.name):
            continue
        if listar_pdfs(d):
            resultado.append(d)
    return resultado


def _grupos_flat(pdfs: list[Path]) -> list[tuple[str, list[Path]]]:
    """Agrupa PDFs planos por complemento (nome → conteúdo como fallback)."""
    grupos: dict[str, list[Path]] = {}
    for p in pdfs:
        comp = _normalizar_complemento(p.stem)
        if comp == "?":
            comp = _complemento_pdf(p)
        grupos.setdefault(comp, []).append(p)
    return sorted(grupos.items())


# ─── API pública ─────────────────────────────────────────────

def scan_mes(pasta_mes: Path) -> list[LoteAgrupadora]:
    """Varre uma pasta de mês e devolve até N lotes (um por agrupadora)."""
    ano, mes = _extrair_ano_mes(pasta_mes)
    lotes: list[LoteAgrupadora] = []
    subpastas = _subpastas_agrupadora(pasta_mes)

    if subpastas:
        # Caso: cada subpasta = 1 lote (padrão 2020-2022, 2024-FEV).
        for d in subpastas:
            pdfs = listar_pdfs(d)
            if not pdfs:
                continue
            comp = _complemento_grupo(d.name, pdfs)
            fmt = detectar_formato(pdfs)
            consumidos = [ArquivoIngest(p, "ignorar") for p in pdfs]
            log.debug(
                "[scanner] %d/%02d  subpasta=%s  comp=%s  fmt=%s  pdfs=%d",
                ano, mes, d.name, comp, fmt, len(pdfs),
            )
            lotes.append(LoteAgrupadora(
                ano=ano, mes=mes,
                complemento_provavel=comp,
                formato=fmt,
                arquivos_consumidos=consumidos,
            ))
    else:
        # Caso: PDFs planos no nível do mês (padrão 2023-2026).
        pdfs = listar_pdfs(pasta_mes)
        if not pdfs:
            return []
        for comp, grupo in _grupos_flat(pdfs):
            fmt = detectar_formato(grupo)
            consumidos = [ArquivoIngest(p, "ignorar") for p in grupo]
            log.debug(
                "[scanner] %d/%02d  comp=%s  fmt=%s  pdfs=%d",
                ano, mes, comp, fmt, len(grupo),
            )
            lotes.append(LoteAgrupadora(
                ano=ano, mes=mes,
                complemento_provavel=comp,
                formato=fmt,
                arquivos_consumidos=consumidos,
            ))

    return lotes
