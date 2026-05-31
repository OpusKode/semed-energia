"""
Classificação de formato de um grupo de arquivos pertencentes a uma
agrupadora (já agrupados pelo scanner).

Formatos:
- unico        : 1 PDF com 1 agrupadora (capa + detalhes juntos).
- consolidado  : 1 PDF gigante com várias agrupadoras dentro.
- fragmentado  : vários PDFs (capa separada dos detalhes).
- pasta_mista  : vários PDFs com versões duplicadas / comprovantes / relações.
- desconhecido : não classificável (logar e pular).

Reaproveita as heurísticas do parser (`parser.patterns`) em vez de
reinventá-las.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from parser import patterns

from ingest.tipos import Formato

# ─── Heurísticas de nome de arquivo ──────────────────────────
RE_COMPROVANTE = re.compile(r"compro|pagam|\bpaga\b", re.IGNORECASE)
RE_RELATORIO = re.compile(r"relat[óo]rio|\.docx", re.IGNORECASE)
RE_RELACAO = re.compile(r"rela[çc][ãa]o", re.IGNORECASE)


@dataclass
class InfoPDF:
    """Fatos sobre um PDF, extraídos uma única vez."""
    caminho: Path
    paginas: int
    capas_reais: list[int]   # índices de páginas-capa (FA + DOCUMENTO, dedup por doc)
    documentos: list[str]    # documentos distintos, na ordem de aparição
    tem_relacao: bool        # contém "RELAÇÃO DE FATURAS AGRUPADORAS"
    tem_cliente: bool        # contém "CLIENTE:"


def capas_reais_doc(doc: "fitz.Document") -> tuple[list[int], list[str]]:
    """Páginas que são capas reais de agrupadora.

    Uma capa real tem "FATURA AGRUPADORA" + um número de documento válido
    (regex `parser.patterns.DOCUMENTO`). Fichas de compensação e boletos
    repetem o texto "FATURA AGRUPADORA" e às vezes o próprio documento da
    capa — por isso deduplicamos: só a PRIMEIRA página de cada documento
    distinto conta como início de uma agrupadora.
    """
    paginas: list[int] = []
    documentos: list[str] = []
    vistos: set[str] = set()
    for i in range(len(doc)):
        texto = doc[i].get_text()
        if not patterns.PAGINA_CAPA.search(texto):
            continue
        m = patterns.DOCUMENTO.search(texto)
        if not m:
            continue
        documento = m.group(1)
        if documento in vistos:
            continue
        vistos.add(documento)
        paginas.append(i)
        documentos.append(documento)
    return paginas, documentos


def analisar_pdf(caminho: Path) -> InfoPDF:
    """Abre o PDF uma vez e coleta os fatos relevantes para a ingestão."""
    doc = fitz.open(str(caminho))
    try:
        capas, docs = capas_reais_doc(doc)
        limite = min(len(doc), 80)
        texto = "\n".join(doc[i].get_text() for i in range(limite))
        return InfoPDF(
            caminho=caminho,
            paginas=len(doc),
            capas_reais=capas,
            documentos=docs,
            tem_relacao=bool(patterns.PAGINA_DETALHE.search(texto)),
            tem_cliente="CLIENTE:" in texto,
        )
    finally:
        doc.close()


def detectar_formato(arquivos: list[Path]) -> Formato:
    """Classifica o conjunto de arquivos de UMA agrupadora num `Formato`."""
    pdfs = sorted(
        (a for a in arquivos if a.suffix.lower() == ".pdf"),
        key=lambda p: p.name.lower(),
    )
    if not pdfs:
        return "desconhecido"

    # ── 1 arquivo só ───────────────────────────────────────
    if len(pdfs) == 1:
        info = analisar_pdf(pdfs[0])
        if len(info.capas_reais) > 1:
            return "consolidado"
        if len(info.capas_reais) == 1:
            return "unico"
        return "desconhecido"

    # ── vários arquivos ────────────────────────────────────
    nomes_suspeitos = any(
        RE_COMPROVANTE.search(p.stem)
        or RE_RELATORIO.search(p.name)
        or RE_RELACAO.search(p.name)
        for p in pdfs
    )

    # Conta capas "puras": PDF curto (≤2 páginas) com exatamente 1 capa real.
    capas_puras = 0
    for p in pdfs:
        info = analisar_pdf(p)
        if info.paginas <= 2 and len(info.capas_reais) == 1:
            capas_puras += 1

    if nomes_suspeitos or capas_puras > 1:
        return "pasta_mista"
    if capas_puras == 1:
        return "fragmentado"
    return "desconhecido"
