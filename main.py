"""
SEMED Energia — Orquestrador principal.

Fluxo por PDF:
    1. Hash SHA-256                       (Camada 1 de dedup)
    2. Classifier (PyMuPDF)               — tipos de pagina + CNPJ + concessionaria
    3. Parser capa                        — dados da agrupadora
    4. Dedup documento                    (Camada 2 de dedup)
    5. Parser B3 e A4                     — faturas individuais
    6. Dedup por nota fiscal              (Camada 3 de dedup)
    7. Validacao de integridade           — 3 camadas
    8. Persistencia                       — agrupadora + faturas + tributos...
    9. Mover com nome padronizado         — processados/ ou duplicados/ ou erros/
    10. Registrar arquivo_processado

Uso:
    python main.py                # processa entrada/
    python main.py --dry-run      # nao persiste no banco, nao move arquivos
    python main.py --no-move      # persiste mas nao move os PDFs
"""
import argparse
import sys
import traceback
from pathlib import Path
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    PASTA_ENTRADA, PASTA_PROCESSADOS, PASTA_DUPLICADOS, PASTA_ERROS,
    TODAS_AS_PASTAS,
)
from utils.logger import configurar_logging
from utils.file_manager import (
    calcular_hash_sha256, gerar_nome_padrao, mover_com_rename,
    SUFIXO_DUP_HASH, SUFIXO_DUP_DOC, SUFIXO_ERRO, SUFIXO_INCOMPLETA,
)
from parser.classifier import classificar_pdf
from parser.capa_parser import parsear_capa
from parser.detalhe_parser import parsear_pagina_b3, parsear_pagina_a4
from validator.integrity import validar_tudo

import fitz  # PyMuPDF — abrimos 1x e reutilizamos entre classifier/capa
import pdfplumber


# =============================================================
# Estrutura de estatisticas
# =============================================================

class Stats:
    def __init__(self):
        self.importados = 0
        self.duplicados_hash = 0
        self.duplicados_doc = 0
        self.duplicados_nf = 0
        self.erros = 0
        self.faturas_importadas = 0
        self.faturas_com_erro = 0
        self.warnings_validacao = 0
        self.detalhes = []

    def linha(self, texto):
        self.detalhes.append(texto)


# =============================================================
# Processamento de um PDF
# =============================================================

def processar_pdf(pdf_path: Path, session, stats: Stats, logger,
                  dry_run: bool = False, mover: bool = True,
                  arquivo_origem_real: str | None = None):
    """
    Processa um PDF ponta-a-ponta.
    Se dry_run=True, nao toca no banco e nao move arquivos.
    Se mover=False, persiste no banco mas nao move o PDF.
    arquivo_origem_real: caminho original dentro de FATURAS - SEMED/
        (usado no banco em vez de pdf_path.name quando fornecido).
    """
    from dedup.detector import DuplicataDetector
    from db.repository import (
        salvar_agrupadora, salvar_fatura_individual, registrar_arquivo,
        atualizar_status_agrupadora,
    )

    logger.info(f"Processando: {pdf_path.name}")
    dados_capa = None
    dados_capa_dict = None
    file_hash = calcular_hash_sha256(pdf_path)
    tamanho = pdf_path.stat().st_size
    detector = DuplicataDetector(session) if (session and not dry_run) else None

    # Validacao explicita do modo: se detector nao pode rodar, as tres camadas
    # de dedup (hash, documento e nota fiscal) ficam desativadas. Em modo
    # persist subsequente, duplicatas podem acabar entrando no banco — por
    # isso avisamos claramente aqui.
    if detector is None:
        motivo = []
        if session is None:
            motivo.append("sem sessao DB")
        if dry_run:
            motivo.append("dry-run")
        logger.warning(
            f"  Dedup DESATIVADA ({', '.join(motivo) or 'motivo desconhecido'}) "
            f"— camadas C1/C2/C3 serao PULADAS para {pdf_path.name}. "
            f"Em modo persist, duplicatas podem entrar no banco."
        )

    # Abrimos o PDF com PyMuPDF UMA vez e compartilhamos entre o classifier
    # e o parser da capa. pdfplumber (detalhe B3/A4) e uma lib diferente e
    # continua abrindo separadamente adiante.
    try:
        fitz_doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Erro ao abrir PDF: {e}")

    try:
        # -------------------- CAMADA 1: HASH ---------------------
        if detector is not None:
            r = detector.verificar_por_hash(file_hash)
            if r.eh_duplicata:
                try:
                    dados_capa = parsear_capa(pdf_path, doc=fitz_doc)
                    dados_capa_dict = dados_capa.to_dict()
                except Exception as e:
                    # Fallback explicito: mesmo sem metadados da capa, seguimos
                    # movendo o duplicado para a pasta correta e registrando no banco.
                    logger.warning(
                        f"  Falha ao parsear capa de duplicata {pdf_path.name}: {e}. "
                        f"Prosseguindo sem metadados."
                    )
                    dados_capa = None
                    dados_capa_dict = None
                logger.warning(f"  DUP-HASH — {r.mensagem}")
                destino = None
                if mover:
                    destino = mover_com_rename(
                        pdf_path, PASTA_DUPLICADOS, dados_capa_dict, SUFIXO_DUP_HASH
                    )
                try:
                    registrar_arquivo(
                        session, pdf_path.name, file_hash,
                        resultado="duplicado_hash", tamanho_bytes=tamanho,
                        documento=(dados_capa_dict or {}).get("documento"),
                        nome_padronizado=destino.name if destino else None,
                    )
                    session.commit()
                except Exception:
                    # Hash já registrado (ex.: reimport idempotente) — segue
                    # contando como duplicata sem quebrar.
                    session.rollback()
                stats.duplicados_hash += 1
                stats.linha(f"DUP-HASH: {pdf_path.name}")
                return

        # -------------------- CLASSIFIER ----------------------
        cls = classificar_pdf(pdf_path, doc=fitz_doc)
        if cls.erro:
            raise RuntimeError(f"Erro no classifier: {cls.erro}")
        if not cls.eh_equatorial:
            raise RuntimeError("PDF nao e da Equatorial Para")

        # -------------------- PARSER CAPA ---------------------
        dados_capa = parsear_capa(pdf_path, doc=fitz_doc)
        dados_capa_dict = dados_capa.to_dict()
    finally:
        fitz_doc.close()

    # -------------------- CAMADA 2: DOCUMENTO --------------
    if detector is not None and dados_capa.documento:
        r = detector.verificar_documento(dados_capa.documento)
        if r.eh_duplicata:
            logger.warning(f"  DUP-DOC — {r.mensagem}")
            destino = None
            if mover:
                destino = mover_com_rename(
                    pdf_path, PASTA_DUPLICADOS, dados_capa_dict, SUFIXO_DUP_DOC
                )
            try:
                registrar_arquivo(
                    session, pdf_path.name, file_hash,
                    resultado="duplicado_doc", tamanho_bytes=tamanho,
                    documento=dados_capa.documento,
                    nome_padronizado=destino.name if destino else None,
                )
                session.commit()
            except Exception:
                # Arquivo/hash já registrado (reimport idempotente) — segue.
                session.rollback()
            stats.duplicados_doc += 1
            stats.linha(f"DUP-DOC: {pdf_path.name} ({dados_capa.documento})")
            return

    # -------------------- PARSERS B3 / A4 -----------------
    # Extrai TODAS as faturas primeiro (sem filtrar por dedup C3 ainda).
    # Motivo: a validacao estrutural precisa comparar o conjunto completo
    # contra o agregado da capa (qtd_esperada, somas, etc). Se filtrassemos
    # duplicadas aqui e a validacao falhasse depois, as NFs teriam sido
    # "consumidas" no contador de dedup sem a importacao correspondente.
    faturas = []
    erros_fatura = []

    with pdfplumber.open(str(pdf_path)) as pdf_obj:
        for p in cls.paginas:
            if p.tipo == "detalhe_b3":
                for f in parsear_pagina_b3(pdf_obj.pages[p.numero], p.numero):
                    faturas.append(f)
            elif p.tipo == "detalhe_a4":
                f = parsear_pagina_a4(pdf_obj.pages[p.numero], p.numero)
                if f is None:
                    continue
                faturas.append(f)

    logger.info(
        f"  Extraidas {len(faturas)} faturas "
        f"(esperadas {dados_capa.qtd_faturas_esperada})"
    )

    # -------------------- VALIDACAO ---------------------
    # Rodamos ANTES da dedup C3. Se a validacao falhar, nao incrementamos
    # o contador de duplicadas — o PDF sera rejeitado inteiro e as NFs
    # podem ser reprocessadas em um novo arquivo no futuro.
    resumo = validar_tudo(dados_capa, faturas, eh_equatorial=cls.eh_equatorial)
    vstats = resumo.estatisticas()
    logger.info(
        f"  Validacao: OK={vstats['ok']} WARN={vstats['warn']} ERRO={vstats['erro']}"
    )
    stats.warnings_validacao += vstats["warn"]
    for e in resumo.erros:
        logger.error(f"    [VALID ERRO C{e.camada}] {e.tipo}: {e.mensagem}")
    for w in resumo.warnings[:5]:
        nota = f" [NF {w.fatura_nota}]" if w.fatura_nota else ""
        logger.warning(f"    [VALID WARN C{w.camada}] {w.tipo}{nota}: {w.mensagem}")
    if len(resumo.warnings) > 5:
        logger.warning(f"    ... e mais {len(resumo.warnings)-5} warnings")

    if not resumo.pode_persistir:
        raise RuntimeError(
            "Validacao estrutural falhou (nao persiste). "
            f"Erros: {[e.mensagem for e in resumo.erros]}"
        )

    # -------------------- CAMADA 3: NOTA FISCAL (pos-validacao) ----------
    # Agora que a validacao passou, filtra NFs ja existentes no banco.
    # Assim o contador de dedup so e incrementado para faturas que
    # efetivamente serao (ou ja foram) persistidas.
    pulou_por_nota = 0
    if detector is not None:
        faturas_filtradas = []
        for f in faturas:
            if f.nota_fiscal:
                r = detector.verificar_nota_fiscal(f.nota_fiscal)
                if r.eh_duplicata:
                    logger.warning(
                        f"  Nota {f.nota_fiscal} ja existe (pulando)")
                    pulou_por_nota += 1
                    stats.duplicados_nf += 1
                    continue
            faturas_filtradas.append(f)
        faturas = faturas_filtradas
        if pulou_por_nota:
            logger.info(f"  Dedup C3 pos-validacao: {pulou_por_nota} NF(s) ja existiam")

    # -------------------- PERSISTENCIA --------------------
    agrupadora_id = None
    if not dry_run and session is not None:
        ag = salvar_agrupadora(
            session, dados_capa,
            arquivo_origem=arquivo_origem_real or pdf_path.name,
        )
        agrupadora_id = ag.id
        for f in faturas:
            try:
                salvar_fatura_individual(session, ag.id, f)
            except Exception as ex:
                erros_fatura.append(f"NF {f.nota_fiscal}: {ex}")

        status = "incompleta" if erros_fatura else "completa"
        atualizar_status_agrupadora(
            session, ag.id, status,
            faturas_importadas=len(faturas) - len(erros_fatura),
            faturas_com_erro=len(erros_fatura),
            erros_log="\n".join(erros_fatura) if erros_fatura else None,
        )
    else:
        status = "completa"

    # -------------------- MOVE COM RENAME -----------------
    sufixo = SUFIXO_INCOMPLETA if status == "incompleta" else ""
    destino = None
    if mover and not dry_run:
        destino = mover_com_rename(
            pdf_path, PASTA_PROCESSADOS, dados_capa_dict, sufixo
        )

    if session is not None and not dry_run:
        registrar_arquivo(
            session, pdf_path.name, file_hash,
            resultado="importado", tamanho_bytes=tamanho,
            documento=dados_capa.documento,
            agrupadora_id=agrupadora_id,
            nome_padronizado=destino.name if destino else None,
        )
        session.commit()

    logger.info(f"  OK {status} — {len(faturas)} faturas"
                + (f" -> {destino.name}" if destino else ""))
    stats.importados += 1
    stats.faturas_importadas += len(faturas) - len(erros_fatura)
    stats.faturas_com_erro += len(erros_fatura)
    nome_final = destino.name if destino else gerar_nome_padrao(dados_capa_dict, sufixo)
    stats.linha(f"OK  {pdf_path.name:30s} -> {nome_final}")


# =============================================================
# Relatorio final
# =============================================================

def imprimir_relatorio(stats: Stats, pasta: Path, logger, dry_run: bool):
    logger.info("=" * 60)
    logger.info("  RELATORIO DE IMPORTACAO  —  " + datetime.now().strftime("%d/%m/%Y %H:%M"))
    if dry_run:
        logger.info("  [DRY-RUN: nenhuma alteracao persistida]")
    logger.info("=" * 60)
    total = stats.importados + stats.duplicados_hash + stats.duplicados_doc + stats.erros
    logger.info(f"  Arquivos encontrados   : {total}")
    logger.info(f"  Importados com sucesso : {stats.importados}")
    logger.info(f"  Duplicatas por hash    : {stats.duplicados_hash}")
    logger.info(f"  Duplicatas por doc     : {stats.duplicados_doc}")
    logger.info(f"  Notas pulou (C3)       : {stats.duplicados_nf}")
    logger.info(f"  Com erros              : {stats.erros}")
    logger.info(f"  Faturas importadas     : {stats.faturas_importadas}")
    logger.info(f"  Faturas com erro       : {stats.faturas_com_erro}")
    logger.info(f"  Warnings de validacao  : {stats.warnings_validacao}")
    logger.info("-" * 60)
    for linha in stats.detalhes:
        logger.info(f"  {linha}")
    logger.info("=" * 60)


# =============================================================
# Modo historico
# =============================================================

def _processar_modo_historico(args, logger, session, stats: Stats):
    """
    Varre FATURAS - SEMED/ com o orquestrador de ingestão e processa
    cada lote com `processar_pdf`. Exceções por lote são logadas e o
    loop continua — sem abortar tudo por um PDF problemático.
    """
    import tempfile
    from ingest.orquestrador import expandir_pasta_historica

    raiz = Path(args.raiz)
    if not raiz.exists():
        logger.error(f"[historico] Raiz nao encontrada: {raiz}")
        return

    dry_run: bool = args.dry_run

    # Em dry-run usamos um diretorio temporario para os PDFs logicos gerados
    # (splits/merges), evitando poluir entrada/.
    if dry_run:
        tmp_dir = tempfile.mkdtemp(prefix="semed_ingest_")
        destino = Path(tmp_dir)
    else:
        destino = PASTA_ENTRADA

    logger.info(f"[historico] Varrendo: {raiz}")
    logger.info(f"[historico] PDFs logicos em: {destino}")

    n_lotes = 0
    try:
        for lote in expandir_pasta_historica(raiz, destino):
            n_lotes += 1
            pdf = lote.pdf_logico
            if pdf is None or not pdf.exists():
                logger.warning(
                    f"[historico] Lote {lote.ano}/{lote.mes:02d} "
                    f"{lote.complemento_provavel} sem pdf_logico — pulando"
                )
                stats.erros += 1
                continue

            # Caminho original do(s) arquivo(s) fonte, para auditoria no banco.
            fontes = [str(a.caminho) for a in lote.arquivos_consumidos]
            origem_real = fontes[0] if fontes else pdf.name

            try:
                processar_pdf(
                    pdf, session, stats, logger,
                    dry_run=dry_run,
                    mover=False,  # PDFs logicos ficam no destino; nao mover
                    arquivo_origem_real=origem_real,
                )
            except Exception as e:
                logger.error(
                    f"[historico] Erro em lote {lote.ano}/{lote.mes:02d} "
                    f"{lote.complemento_provavel} ({pdf.name}): {e}"
                )
                logger.debug(traceback.format_exc())
                stats.erros += 1
                stats.linha(
                    f"ERRO: {lote.complemento_provavel} "
                    f"{lote.ano}/{lote.mes:02d} — {e}"
                )
                if session is not None:
                    session.rollback()
    finally:
        if dry_run:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(f"[historico] {n_lotes} lote(s) processado(s)")


# =============================================================
# Entry point
# =============================================================

def main():
    ap = argparse.ArgumentParser(description="SEMED Energia — importador de faturas")
    ap.add_argument("--dry-run", action="store_true",
                    help="Executa o fluxo sem persistir no banco e sem mover arquivos")
    ap.add_argument("--no-move", action="store_true",
                    help="Persiste no banco mas deixa os PDFs em entrada/")
    ap.add_argument("--pasta", default=str(PASTA_ENTRADA),
                    help="Pasta de entrada (default: entrada/)")
    ap.add_argument("--modo", choices=["normal", "historico"], default="normal",
                    help="normal: processa entrada/; historico: varre FATURAS - SEMED/")
    ap.add_argument("--raiz", default=None,
                    help="Raiz do historico (requerido com --modo historico)")
    args = ap.parse_args()

    logger = configurar_logging()
    logger.info("=" * 60)
    logger.info("  SEMED Energia — Iniciando processamento")
    if args.dry_run:
        logger.info("  MODO DRY-RUN (sem DB, sem mover)")
    if args.modo == "historico":
        logger.info("  MODO HISTORICO")
    logger.info("=" * 60)

    # Criar pastas se nao existirem
    for p in TODAS_AS_PASTAS:
        p.mkdir(parents=True, exist_ok=True)

    # Conectar no banco (se nao for dry-run)
    session = None
    if not args.dry_run:
        try:
            from db.connection import get_session, testar_conexao
            testar_conexao()
            session = get_session()
            logger.info("Conexao com o banco OK")
        except Exception as e:
            logger.error(f"Falha na conexao: {e}")
            logger.error("Execute setup.py primeiro (ou use --dry-run)")
            sys.exit(1)

    stats = Stats()

    # ── Modo historico ────────────────────────────────────────
    if args.modo == "historico":
        if not args.raiz:
            logger.error("--raiz e obrigatorio no modo historico")
            sys.exit(1)
        _processar_modo_historico(args, logger, session, stats)
        if session is not None:
            session.close()
        imprimir_relatorio(stats, Path(args.raiz), logger, args.dry_run)
        return

    # ── Modo normal (entrada/) ────────────────────────────────
    pasta = Path(args.pasta)
    pdfs = sorted(pasta.glob("*.pdf"))
    if not pdfs:
        logger.info(f"Nenhum PDF em {pasta}/")
        return

    logger.info(f"Encontrados {len(pdfs)} PDF(s)")

    for pdf in pdfs:
        try:
            processar_pdf(
                pdf, session, stats, logger,
                dry_run=args.dry_run,
                mover=(not args.no_move) and (not args.dry_run),
            )
        except Exception as e:
            logger.error(f"ERRO FATAL em {pdf.name}: {e}")
            logger.debug(traceback.format_exc())
            stats.erros += 1
            stats.linha(f"ERRO: {pdf.name} — {e}")
            if not args.dry_run and not args.no_move:
                try:
                    from utils.file_manager import mover_com_rename
                    mover_com_rename(pdf, PASTA_ERROS, None, SUFIXO_ERRO)
                except Exception:
                    pass
            if session is not None:
                session.rollback()

    if session is not None:
        session.close()

    imprimir_relatorio(stats, pasta, logger, args.dry_run)


if __name__ == "__main__":
    main()
