"""
Classificação arquivo-a-arquivo para pastas mistas.

Numa pasta mista coexistem: capas, relações, versões duplicadas e
comprovantes de pagamento. Este módulo separa o que deve ser usado
do que deve ser descartado.

Regras (em ordem de prioridade):
1. Nome contém comprovante / compro / paga → comprovante, descartar.
2. Nome contém relatório / .docx → relatorio, descartar.
3. PDF ≤2 páginas + FATURA AGRUPADORA + DOCUMENTO → capa (candidato).
4. PDF sem capa + RELAÇÃO ou CLIENTE → detalhe.
5. PDF >5 páginas + capa → capa+detalhe (usar como único).
6. Múltiplos candidatos a capa → preferir capa+detalhe; se não houver,
   manter só o arquivo com maior mtime.

Heurística de seleção: se existe um arquivo capa+detalhe, ele é suficiente
— os arquivos de capa solta e detalhes separados são versões parciais e
vão para descartados. Documenta a escolha em `aviso`.
"""
import logging
from pathlib import Path

from ingest.detector_formato import RE_COMPROVANTE, RE_RELATORIO, analisar_pdf
from ingest.tipos import ArquivoIngest

log = logging.getLogger("semed.ingest.classifier_pasta")


def _classificar_arquivo(p: Path) -> ArquivoIngest:
    nome = p.stem

    # ── 1. comprovante por nome ───────────────────────────────
    if RE_COMPROVANTE.search(nome):
        return ArquivoIngest(p, "comprovante", "nome indica comprovante de pagamento")

    # ── 2. relatório por nome / extensão ─────────────────────
    if RE_RELATORIO.search(p.name):
        return ArquivoIngest(p, "relatorio", "nome indica relatório")

    # ── 3-5. inspeção de conteúdo ─────────────────────────────
    info = analisar_pdf(p)

    if info.paginas <= 2 and info.capas_reais:
        return ArquivoIngest(p, "capa", f"≤2 páginas com capa válida (doc={info.documentos[0]})")

    if info.paginas > 5 and info.capas_reais:
        return ArquivoIngest(
            p, "capa+detalhe",
            f"{info.paginas} páginas com capa (doc={info.documentos[0]})"
        )

    if info.tem_relacao or info.tem_cliente:
        return ArquivoIngest(p, "detalhe", f"{info.paginas} páginas de detalhe")

    return ArquivoIngest(p, "ignorar", "conteúdo não identificado")


def classificar_arquivos(
    pasta: Path,
) -> tuple[list[ArquivoIngest], list[ArquivoIngest]]:
    """Classifica todos os PDFs de `pasta` e divide em (usar, descartar).

    Returns:
        usar     : arquivos a consumir para montar o PDF lógico.
        descartar: arquivos descartados (logados, não usados).
    """
    pdfs = sorted(
        (p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.name.lower(),
    )

    classificados = [_classificar_arquivo(p) for p in pdfs]

    # Separa por papel
    capas_detalhe = [a for a in classificados if a.papel == "capa+detalhe"]
    capas = [a for a in classificados if a.papel == "capa"]
    detalhes = [a for a in classificados if a.papel == "detalhe"]
    descartar_base = [a for a in classificados if a.papel in ("comprovante", "relatorio", "ignorar")]

    # ── Regra 5: se existe capa+detalhe, ele é suficiente ────
    if capas_detalhe:
        # Escolhe o com maior mtime se houver mais de um.
        escolhido = max(capas_detalhe, key=lambda a: a.caminho.stat().st_mtime)
        if len(capas_detalhe) > 1:
            log.info(
                "[classifier_pasta] múltiplos capa+detalhe em %s — escolhido %s (mtime mais recente)",
                pasta.name, escolhido.caminho.name,
            )
        usar = [escolhido]
        descartar = (
            descartar_base
            + [a for a in capas_detalhe if a is not escolhido]
            + capas
            + detalhes
        )
        return usar, descartar

    # ── Regra 6: seleciona entre múltiplas capas puras ───────
    if len(capas) > 1:
        escolhida = max(capas, key=lambda a: a.caminho.stat().st_mtime)
        log.info(
            "[classifier_pasta] múltiplas capas em %s — escolhida %s (mtime mais recente); "
            "descartando: %s",
            pasta.name,
            escolhida.caminho.name,
            [a.caminho.name for a in capas if a is not escolhida],
        )
        capas = [escolhida]

    usar = capas + detalhes
    descartar = descartar_base
    return usar, descartar
