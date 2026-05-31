"""
Classificador rápido de páginas usando PyMuPDF.

Classifica cada página do PDF em:
- 'capa': página de capa da fatura agrupadora
- 'detalhe_b3': detalhe de instalação baixa tensão
- 'detalhe_a4': detalhe de instalação média tensão
- 'boleto': segunda metade da capa (ficha de compensação)
- 'desconhecido': tipo não identificado

Também valida se o PDF é da Equatorial Pará e extrai o CNPJ.
"""
import fitz  # PyMuPDF
from pathlib import Path
from dataclasses import dataclass

from validate_docbr import CNPJ

from parser import patterns


@dataclass
class PaginaClassificada:
    """Resultado da classificação de uma página."""
    numero: int          # índice (0-based)
    tipo: str            # 'capa', 'detalhe_b3', 'detalhe_a4', 'boleto', 'desconhecido'
    tem_texto: bool      # se a página tem texto extraível
    texto_preview: str   # primeiros 200 chars para debug


@dataclass
class ResultadoClassificacao:
    """Resultado completo da classificação do PDF."""
    arquivo: str
    total_paginas: int
    eh_equatorial: bool
    cnpj_valido: bool
    cnpj: str | None
    paginas: list[PaginaClassificada]
    erro: str | None = None

    @property
    def paginas_capa(self) -> list[PaginaClassificada]:
        return [p for p in self.paginas if p.tipo == "capa"]

    @property
    def paginas_detalhe(self) -> list[PaginaClassificada]:
        return [p for p in self.paginas if p.tipo.startswith("detalhe")]

    @property
    def paginas_b3(self) -> list[PaginaClassificada]:
        return [p for p in self.paginas if p.tipo == "detalhe_b3"]

    @property
    def paginas_a4(self) -> list[PaginaClassificada]:
        return [p for p in self.paginas if p.tipo == "detalhe_a4"]


def classificar_pdf(
    caminho: str | Path,
    doc: "fitz.Document | None" = None,
) -> ResultadoClassificacao:
    """
    Classifica todas as páginas do PDF usando PyMuPDF (~0.01s/página).

    Args:
        caminho: caminho do arquivo PDF (usado para metadados — `arquivo`).
        doc: `fitz.Document` já aberto. Quando fornecido, NÃO é fechado
            aqui — a responsabilidade pelo ciclo de vida fica com quem
            abriu. Permite reutilizar a mesma abertura entre classifier
            e parser da capa, evitando abrir o mesmo PDF 2x.

    Returns:
        ResultadoClassificacao com tipo de cada página
    """
    caminho = Path(caminho)
    paginas = []
    eh_equatorial = False
    cnpj_encontrado = None
    cnpj_valido = False

    close_after = False
    pdf = doc
    if pdf is None:
        try:
            pdf = fitz.open(str(caminho))
            close_after = True
        except Exception as e:
            return ResultadoClassificacao(
                arquivo=caminho.name,
                total_paginas=0,
                eh_equatorial=False,
                cnpj_valido=False,
                cnpj=None,
                paginas=[],
                erro=f"Erro ao abrir PDF: {e}",
            )

    try:
        for i in range(len(pdf)):
            page = pdf[i]
            texto = page.get_text()
            tem_texto = len(texto.strip()) > 50

            tipo = _classificar_pagina(texto, i)

            # Na primeira página, validar concessionária e CNPJ
            if i == 0:
                eh_equatorial = bool(patterns.CONCESSIONARIA.search(texto))
                m = patterns.CLIENTE_CNPJ.search(texto)
                if m:
                    cnpj_encontrado = m.group(1)
                    validador = CNPJ()
                    cnpj_valido = validador.validate(cnpj_encontrado)

            paginas.append(PaginaClassificada(
                numero=i,
                tipo=tipo,
                tem_texto=tem_texto,
                texto_preview=texto[:200].replace("\n", " "),
            ))

    finally:
        if close_after:
            pdf.close()

    return ResultadoClassificacao(
        arquivo=caminho.name,
        total_paginas=len(paginas),
        eh_equatorial=eh_equatorial,
        cnpj_valido=cnpj_valido,
        cnpj=cnpj_encontrado,
        paginas=paginas,
    )


def _classificar_pagina(texto: str, indice: int) -> str:
    """Classifica uma página individual pelo seu conteúdo."""

    # Página de capa: tem "FATURA AGRUPADORA" e dados de energia
    if indice == 0 and patterns.PAGINA_CAPA.search(texto):
        return "capa"

    # Páginas de detalhe: têm "RELAÇÃO DE FATURAS"
    if patterns.PAGINA_DETALHE.search(texto):
        # Distinguir B3 de A4
        if patterns.TENSAO_A4.search(texto):
            return "detalhe_a4"
        else:
            return "detalhe_b3"

    # Se tem "Ficha de Compensação" é a parte do boleto
    if "Ficha de Compensação" in texto or "VALOR COBRADO" in texto:
        return "boleto"

    return "desconhecido"
