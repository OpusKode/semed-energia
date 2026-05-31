"""
Splitter de PDFs consolidados.

Um PDF consolidado contém várias agrupadoras: cada capa real é seguida
pelas páginas de detalhe daquela agrupadora. Este módulo encontra as
capas reais e quebra o PDF em N PDFs lógicos, um por agrupadora.
"""
from pathlib import Path

import fitz  # PyMuPDF

from ingest.detector_formato import capas_reais_doc


def dividir_consolidado(pdf_path: Path, destino: Path) -> list[Path]:
    """Quebra um PDF consolidado em N PDFs lógicos (um por agrupadora).

    Cada capa real (página com "FATURA AGRUPADORA" + documento válido,
    deduplicada por documento) inicia uma agrupadora. O fim é a página
    anterior à próxima capa real, ou o fim do PDF.

    Returns:
        Lista dos PDFs gerados em `destino`, na ordem em que aparecem.
    """
    destino.mkdir(parents=True, exist_ok=True)
    src = fitz.open(str(pdf_path))
    try:
        capas, _ = capas_reais_doc(src)
        if not capas:
            return []

        gerados: list[Path] = []
        for idx, inicio in enumerate(capas):
            if idx + 1 < len(capas):
                fim = capas[idx + 1] - 1
            else:
                fim = len(src) - 1

            novo = fitz.open()
            novo.insert_pdf(src, from_page=inicio, to_page=fim)
            saida = destino / f"{pdf_path.stem}_split_{idx + 1}.pdf"
            novo.save(str(saida))
            novo.close()
            gerados.append(saida)
        return gerados
    finally:
        src.close()
