"""
API pública do módulo de ingestão.

    from ingest.orquestrador import expandir_pasta_historica

    for lote in expandir_pasta_historica(raiz, destino):
        processar_pdf(lote.pdf_logico, ...)
"""
import hashlib
import logging
import re
from pathlib import Path
from typing import Iterator

import fitz

from ingest.classifier_pasta import classificar_arquivos
from ingest.detector_formato import analisar_pdf
from ingest.merger import fundir_fragmentado
from ingest.scanner import _complemento_grupo, listar_pdfs, scan_mes
from ingest.splitter import dividir_consolidado
from ingest.tipos import ArquivoIngest, LoteAgrupadora

log = logging.getLogger("semed.ingest")


# ─── Utilitários ─────────────────────────────────────────────

_RE_PASTA_MES = re.compile(
    r"^\d{1,2}[^0-9]"                          # inicia com 1 ou 2 dígitos (ex: "5_-", "10-")
    r"|JANEIRO|FEVEREIRO|MAR[CÇ]O|ABRIL|MAIO"  # ou contém nome do mês em português
    r"|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO"
    r"|NOVEMBRO|DEZEMBRO",
    re.IGNORECASE,
)


def _e_pasta_mes(pasta: Path) -> bool:
    """Heurística: o nome desta pasta indica um mês específico?"""
    return bool(_RE_PASTA_MES.search(pasta.name))


def _md5(caminho: Path) -> str:
    h = hashlib.md5()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _complemento_do_pdf(caminho: Path) -> str:
    """Lê a primeira página do PDF e extrai o complemento."""
    try:
        doc = fitz.open(str(caminho))
        try:
            texto = doc[0].get_text()
        finally:
            doc.close()
        return _complemento_grupo(texto, [])
    except Exception:
        return "?"


def _achar_pastas_mes(pasta: Path) -> list[Path]:
    """Percorre a hierarquia e retorna as 'pastas de mês'.

    Regras:
    - Se a pasta tem PDFs diretamente → é ela mesma uma pasta_mes.
    - Se a pasta tem subpastas com PDFs diretamente E parece ser uma pasta de
      mês (nome numérico ou nome pt-BR) → é ela mesma uma pasta_mes.
    - Se a pasta tem subpastas com PDFs MAS não parece ser uma pasta de mês
      (ex: pasta de ano "EQUATORIAL - FATURAS - 2022") → cada subpasta com
      PDFs é uma pasta_mes; subpastas sem PDFs são varridas recursivamente.
    - Caso contrário → varre recursivamente todos os subdiretórios.
    """
    pdfs = listar_pdfs(pasta)
    subdirs = [d for d in pasta.iterdir() if d.is_dir()]
    subdir_com_pdf = [d for d in subdirs if listar_pdfs(d)]

    if pdfs:
        # PDFs diretamente aqui → esta pasta é a pasta_mes.
        return [pasta]

    if subdir_com_pdf:
        if _e_pasta_mes(pasta):
            # Pasta de mês com subpastas de agrupadora (ex: OUTUBRO-2020/SEMED-I/).
            return [pasta]
        # Pasta de nível superior (ano, raiz): cada subdir com PDF é uma pasta_mes.
        resultado: list[Path] = list(subdir_com_pdf)
        # Subdirs sem PDF direto podem conter estruturas mais profundas.
        for d in subdirs:
            if d not in subdir_com_pdf:
                resultado.extend(_achar_pastas_mes(d))
        return sorted(resultado, key=lambda p: p.name.lower())

    # Nenhum PDF encontrado neste nível ou nos filhos diretos → descer mais.
    resultados: list[Path] = []
    for d in sorted(subdirs, key=lambda p: p.name.lower()):
        resultados.extend(_achar_pastas_mes(d))
    return resultados


# ─── Materialização de lotes ─────────────────────────────────

def _log_desconhecido(lote: LoteAgrupadora) -> None:
    """Loga diagnóstico detalhado para lotes não classificáveis."""
    pdfs = [a.caminho for a in lote.arquivos_consumidos
            if a.caminho.suffix.lower() == ".pdf"]
    log.warning(
        "[ingest] %d/%02d %s  formato=desconhecido  n_pdfs=%d  — pulando",
        lote.ano, lote.mes, lote.complemento_provavel, len(pdfs),
    )
    for caminho in pdfs[:3]:  # até 3 arquivos para não poluir o log
        try:
            doc = fitz.open(str(caminho))
            try:
                n_pags = len(doc)
                texto = doc[0].get_text()[:400].replace("\n", " ").strip()
            finally:
                doc.close()
        except Exception as e:
            n_pags = -1
            texto = f"<erro ao abrir: {e}>"
        log.warning(
            "  arquivo: %s  paginas=%d  texto[:400]=%r",
            caminho.name, n_pags, texto,
        )


def _log_lote(lote: LoteAgrupadora) -> None:
    n_cons = len(lote.arquivos_consumidos)
    n_total = n_cons + len(lote.arquivos_descartados)
    desc_nomes = [a.caminho.name for a in lote.arquivos_descartados]
    md5 = _md5(lote.pdf_logico) if lote.pdf_logico else "—"
    log.info(
        "[ingest] %d/%02d %s  formato=%s  arq_consumidos=%d/%d  "
        "descartados=%s  pdf_logico=%s  md5=%s",
        lote.ano, lote.mes, lote.complemento_provavel,
        lote.formato, n_cons, n_total,
        desc_nomes or "[]",
        lote.pdf_logico.name if lote.pdf_logico else None,
        md5,
    )


def _classificar_papel_fragmentado(caminho: Path) -> str:
    """Papel de um arquivo num lote fragmentado."""
    info = analisar_pdf(caminho)
    if info.paginas <= 2 and info.capas_reais:
        return "capa"
    if info.tem_relacao or info.tem_cliente:
        return "detalhe"
    return "ignorar"


def _materializar_lote(
    lote: LoteAgrupadora,
    destino: Path,
) -> Iterator[LoteAgrupadora]:
    """Materializa `pdf_logico` e emite 1..N lotes prontos para o parser."""
    fmt = lote.formato

    if fmt == "desconhecido":
        _log_desconhecido(lote)
        return

    # ── unico: aponta para o arquivo original ─────────────────
    if fmt == "unico":
        arq = lote.arquivos_consumidos[0]
        arq.papel = "capa+detalhe"
        arq.motivo = "unico — capa e detalhe no mesmo PDF"
        lote.pdf_logico = arq.caminho
        _log_lote(lote)
        yield lote
        return

    # ── consolidado: split → N sub-lotes ──────────────────────
    if fmt == "consolidado":
        pdf_fonte = lote.arquivos_consumidos[0].caminho
        splits = dividir_consolidado(pdf_fonte, destino)
        for idx, split in enumerate(splits, 1):
            comp = _complemento_do_pdf(split)
            sub = LoteAgrupadora(
                ano=lote.ano,
                mes=lote.mes,
                complemento_provavel=comp,
                formato="consolidado",
                arquivos_consumidos=lote.arquivos_consumidos[:],
                pdf_logico=split,
                avisos=[f"split {idx}/{len(splits)} de {pdf_fonte.name}"],
            )
            _log_lote(sub)
            yield sub
        return

    # ── fragmentado: merger → 1 lote ──────────────────────────
    if fmt == "fragmentado":
        classificados = [
            ArquivoIngest(
                a.caminho,
                _classificar_papel_fragmentado(a.caminho),
                "auto-classificado pelo orquestrador",
            )
            for a in lote.arquivos_consumidos
        ]
        usar = [a for a in classificados if a.papel in ("capa", "detalhe")]
        descartar = [a for a in classificados if a.papel == "ignorar"]

        if not usar:
            log.warning(
                "[ingest] fragmentado sem capa/detalhe: %s/%02d %s",
                lote.ano, lote.mes, lote.complemento_provavel,
            )
            return

        merged = fundir_fragmentado(usar, destino)
        lote.arquivos_consumidos = classificados
        lote.arquivos_descartados = descartar
        lote.pdf_logico = merged
        _log_lote(lote)
        yield lote
        return

    # ── pasta_mista: classifier_pasta → unico ou fragmentado ──
    if fmt == "pasta_mista":
        if not lote.arquivos_consumidos:
            return
        pasta = lote.arquivos_consumidos[0].caminho.parent
        usar, descartar = classificar_arquivos(pasta)
        lote.arquivos_descartados = descartar

        if not usar:
            log.warning(
                "[ingest] pasta_mista sem arquivos usáveis: %d/%02d %s",
                lote.ano, lote.mes, lote.complemento_provavel,
            )
            return

        # Preferência: capa+detalhe único existente.
        if len(usar) == 1 and usar[0].papel == "capa+detalhe":
            lote.arquivos_consumidos = usar
            lote.pdf_logico = usar[0].caminho
            _log_lote(lote)
            yield lote
            return

        # Fragmentado dentro da pasta mista.
        para_fundir = [a for a in usar if a.papel in ("capa", "detalhe", "capa+detalhe")]
        if not para_fundir:
            log.warning(
                "[ingest] pasta_mista sem capa/detalhe usáveis: %d/%02d %s",
                lote.ano, lote.mes, lote.complemento_provavel,
            )
            return

        merged = fundir_fragmentado(para_fundir, destino)
        lote.arquivos_consumidos = usar
        lote.pdf_logico = merged
        _log_lote(lote)
        yield lote


# ─── API pública ─────────────────────────────────────────────

def expandir_pasta_historica(
    raiz: Path,
    destino_pdfs_logicos: Path,
) -> Iterator[LoteAgrupadora]:
    """Varre `raiz` e devolve lotes prontos para o parser.

    Cada lote emitido já tem `pdf_logico` materializado em
    `destino_pdfs_logicos`. Lotes desconhecidos ou sem pdf_logico são
    logados e omitidos.
    """
    destino_pdfs_logicos.mkdir(parents=True, exist_ok=True)
    pastas_mes = _achar_pastas_mes(raiz)
    log.info(
        "[ingest] %d pasta(s) de mês encontrada(s) em %s",
        len(pastas_mes), raiz.name,
    )

    for pasta_mes in pastas_mes:
        try:
            lotes_brutos = scan_mes(pasta_mes)
        except Exception as e:
            log.error("[ingest] erro ao scanear %s: %s", pasta_mes, e)
            continue

        for lote_bruto in lotes_brutos:
            try:
                yield from _materializar_lote(lote_bruto, destino_pdfs_logicos)
            except Exception as e:
                log.error(
                    "[ingest] erro ao materializar lote %d/%02d %s: %s",
                    lote_bruto.ano, lote_bruto.mes,
                    lote_bruto.complemento_provavel, e,
                )
