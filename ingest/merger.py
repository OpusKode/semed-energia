"""
Merger de PDFs fragmentados.

Uma agrupadora pode vir repartida em vários arquivos:
- capa solta (1-2 páginas);
- detalhes / relação (várias páginas);
- eventualmente um anexo extra (mais uma fatura ou relação).

Este módulo concatena tudo num único PDF lógico, na ordem
capa → detalhes → extra, descartando comprovantes e relatórios.
"""
import re
from pathlib import Path

import fitz  # PyMuPDF

from ingest.tipos import ArquivoIngest


def _nome_seguro(texto: str) -> str:
    limpo = re.sub(r"[^\w\-]+", "_", texto).strip("_")
    return limpo or "lote"


def fundir_fragmentado(arquivos: list[ArquivoIngest], destino: Path) -> Path:
    """Funde os arquivos de UMA agrupadora num único PDF lógico.

    Ordem de concatenação: `capa` → `capa+detalhe` → `detalhe` (cada
    grupo ordenado por nome de arquivo, o que mantém `2.pdf` antes de
    `3.pdf`). Arquivos `comprovante` / `relatorio` / `ignorar` não entram.

    Returns:
        Caminho do PDF lógico gerado em `destino`.
    """
    destino.mkdir(parents=True, exist_ok=True)

    def _por_nome(itens: list[ArquivoIngest]) -> list[ArquivoIngest]:
        return sorted(itens, key=lambda a: a.caminho.name.lower())

    capas = _por_nome([a for a in arquivos if a.papel == "capa"])
    combinados = _por_nome([a for a in arquivos if a.papel == "capa+detalhe"])
    detalhes = _por_nome([a for a in arquivos if a.papel == "detalhe"])
    ordenados = capas + combinados + detalhes

    if not ordenados:
        raise ValueError(
            "Nenhum arquivo de capa/detalhe para fundir "
            f"(recebidos: {[a.caminho.name for a in arquivos]})"
        )

    novo = fitz.open()
    try:
        for arq in ordenados:
            src = fitz.open(str(arq.caminho))
            try:
                novo.insert_pdf(src)
            finally:
                src.close()

        base = ordenados[0].caminho.parent.name
        saida = destino / f"{_nome_seguro(base)}_merged.pdf"
        novo.save(str(saida))
    finally:
        novo.close()
    return saida
