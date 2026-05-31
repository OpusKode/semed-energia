"""
Reimport completo do histórico de faturas SEMED (2020–2026).

Fluxo:
  1. Snapshot "antes" do banco.
  2. Confirmação interativa (a não ser que --no-confirm).
  3. Apaga agrupadoras existentes (DELETE via reprocessar_documento).
  4. Processa cada ano em ordem (2020 → 2026) via modo histórico do main.py.
  5. Snapshot "depois".
  6. Relatório CSV + resumo comparativo no terminal.

Uso:
    python scripts/reimport_historico.py                   # completo, interativo
    python scripts/reimport_historico.py --dry-run         # valida lotes, sem persistir
    python scripts/reimport_historico.py --ano 2026        # só um ano
    python scripts/reimport_historico.py --no-confirm      # sem pausa interativa (CI)
"""
import argparse
import csv
import sys
import traceback
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Pasta raiz do histórico (relativa à raiz do projeto)
_PASTA_HISTORICO_DEFAULT = "FATURAS - SEMED"
_ANOS_ORDEM = [2020, 2021, 2022, 2023, 2024, 2025, 2026]


# =============================================================
# Helpers
# =============================================================

def _pasta_ano(raiz: Path, ano: int) -> Path | None:
    """Localiza a subpasta do ano dentro de raiz (suporta variações de nome)."""
    for p in raiz.iterdir():
        if p.is_dir() and str(ano) in p.name:
            return p
    return None


def _apagar_agrupadoras(session) -> int:
    """Remove todas as agrupadoras do banco. Retorna quantas foram apagadas."""
    from db.models import FaturaAgrupadora, ArquivoProcessado
    n = session.query(FaturaAgrupadora).count()
    session.query(FaturaAgrupadora).delete(synchronize_session=False)
    session.query(ArquivoProcessado).delete(synchronize_session=False)
    session.commit()
    return n


# =============================================================
# Processamento de um ano
# =============================================================

def _processar_ano(ano: int, raiz_ano: Path, dry_run: bool, session,
                   logger, stats_globais) -> list[dict]:
    """
    Roda o orquestrador de ingestão para um único ano e retorna lista de
    dicts para o relatório CSV.
    """
    import tempfile
    import shutil
    from ingest.orquestrador import expandir_pasta_historica
    from config import PASTA_ENTRADA
    from main import processar_pdf, Stats

    linhas_csv: list[dict] = []

    if dry_run:
        tmp_dir = tempfile.mkdtemp(prefix=f"semed_ingest_{ano}_")
        destino = Path(tmp_dir)
    else:
        destino = PASTA_ENTRADA

    try:
        for lote in expandir_pasta_historica(raiz_ano, destino):
            pdf = lote.pdf_logico
            fontes = [str(a.caminho) for a in lote.arquivos_consumidos]
            origem_real = fontes[0] if fontes else (pdf.name if pdf else "?")

            linha: dict = {
                "arquivo_origem": origem_real,
                "ano": lote.ano,
                "mes": lote.mes,
                "complemento_provavel": lote.complemento_provavel,
                "formato_detectado": lote.formato,
                "resultado": "PENDENTE",
                "agrupadoras_importadas": 0,
                "faturas_importadas": 0,
                "warnings": 0,
                "erros": "",
            }

            if pdf is None or not pdf.exists():
                linha["resultado"] = "SEM_PDF"
                linha["erros"] = "pdf_logico ausente"
                linhas_csv.append(linha)
                stats_globais["erros"] += 1
                logger.warning(
                    f"[{ano}] {lote.complemento_provavel} "
                    f"{lote.ano}/{lote.mes:02d} — sem pdf_logico"
                )
                continue

            stats_lote = Stats()
            try:
                processar_pdf(
                    pdf, session, stats_lote, logger,
                    dry_run=dry_run,
                    mover=False,
                    arquivo_origem_real=origem_real,
                )
                linha["resultado"] = "OK"
                linha["agrupadoras_importadas"] = stats_lote.importados
                linha["faturas_importadas"] = stats_lote.faturas_importadas
                linha["warnings"] = stats_lote.warnings_validacao
                stats_globais["agrupadoras"] += stats_lote.importados
                stats_globais["faturas"] += stats_lote.faturas_importadas
            except Exception as e:
                linha["resultado"] = "ERRO"
                linha["erros"] = str(e)[:200]
                stats_globais["erros"] += 1
                logger.error(
                    f"[{ano}] {lote.complemento_provavel} "
                    f"{lote.ano}/{lote.mes:02d} — {e}"
                )
                logger.debug(traceback.format_exc())
                if session is not None:
                    session.rollback()

            linhas_csv.append(linha)

    finally:
        if dry_run:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return linhas_csv


# =============================================================
# Entry point
# =============================================================

def main():
    ap = argparse.ArgumentParser(
        description="Reimport completo do histórico SEMED 2020–2026."
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Valida lotes sem apagar nem persistir nada."
    )
    ap.add_argument(
        "--ano", type=int, default=None,
        help="Reimporta só um ano específico (ex: 2026)."
    )
    ap.add_argument(
        "--no-confirm", action="store_true",
        help="Pula confirmação interativa (útil em CI/CD)."
    )
    ap.add_argument(
        "--raiz", default=_PASTA_HISTORICO_DEFAULT,
        help=f"Pasta raiz do histórico (default: {_PASTA_HISTORICO_DEFAULT})."
    )
    args = ap.parse_args()

    from utils.logger import configurar_logging
    logger = configurar_logging()

    raiz = Path(args.raiz)
    if not raiz.exists():
        logger.error(f"Pasta raiz não encontrada: {raiz}")
        sys.exit(1)

    anos = [args.ano] if args.ano else _ANOS_ORDEM
    anos_validos = [a for a in anos if _pasta_ano(raiz, a) is not None]
    if not anos_validos:
        logger.error(f"Nenhuma subpasta de ano encontrada em {raiz}")
        sys.exit(1)

    # ── Snapshot antes ───────────────────────────────────────────────────────
    snap_antes_path = None
    if not args.dry_run:
        try:
            from scripts.snapshot_db import tirar_snapshot
            snap_antes_path = tirar_snapshot()
            logger.info(f"Snapshot ANTES: {snap_antes_path}")
            with open(snap_antes_path, encoding="utf-8") as f:
                import json
                snap_antes = json.load(f)
            n_antes = snap_antes["total_agrupadoras"]
            fat_antes = snap_antes["total_faturas"]
        except Exception as e:
            logger.warning(f"Não foi possível tirar snapshot antes: {e}")
            n_antes, fat_antes = 0, 0
    else:
        logger.info("[dry-run] Snapshot antes pulado.")
        n_antes, fat_antes = 0, 0

    # ── Confirmação interativa ───────────────────────────────────────────────
    session = None
    if not args.dry_run:
        try:
            from db.connection import get_session, testar_conexao
            testar_conexao()
            session = get_session()
        except Exception as e:
            logger.error(f"Falha na conexão com o banco: {e}")
            sys.exit(1)

        if not args.no_confirm:
            resposta = input(
                f"\nApagar {n_antes} agrupadora(s) existente(s) e reimportar? [s/N] "
            ).strip().lower()
            if resposta != "s":
                print("Operação cancelada.")
                session.close()
                sys.exit(0)

        logger.info(f"Apagando {n_antes} agrupadora(s) do banco…")
        apagadas = _apagar_agrupadoras(session)
        logger.info(f"{apagadas} agrupadora(s) removida(s).")

    # ── Loop por ano ─────────────────────────────────────────────────────────
    stats_globais = {"agrupadoras": 0, "faturas": 0, "erros": 0}
    todas_linhas: list[dict] = []

    for ano in anos_validos:
        raiz_ano = _pasta_ano(raiz, ano)
        if raiz_ano is None:
            logger.warning(f"Subpasta para {ano} não encontrada em {raiz} — pulando.")
            continue

        logger.info(f"=== Processando ano {ano} ({raiz_ano.name}) ===")
        linhas = _processar_ano(
            ano, raiz_ano, args.dry_run, session, logger, stats_globais
        )
        todas_linhas.extend(linhas)
        logger.info(
            f"[{ano}] Lotes: {len(linhas)} | "
            f"OK: {sum(1 for l in linhas if l['resultado'] == 'OK')} | "
            f"Erros: {sum(1 for l in linhas if l['resultado'] == 'ERRO')}"
        )

    # ── Snapshot depois ──────────────────────────────────────────────────────
    n_depois, fat_depois = 0, 0
    snap_depois_path = None
    if not args.dry_run:
        try:
            from scripts.snapshot_db import tirar_snapshot
            snap_depois_path = tirar_snapshot()
            logger.info(f"Snapshot DEPOIS: {snap_depois_path}")
            with open(snap_depois_path, encoding="utf-8") as f:
                import json
                snap_depois = json.load(f)
            n_depois = snap_depois["total_agrupadoras"]
            fat_depois = snap_depois["total_faturas"]
        except Exception as e:
            logger.warning(f"Não foi possível tirar snapshot depois: {e}")

    if session is not None:
        session.close()

    # ── Relatório CSV ────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d")
    csv_path = _ROOT / "scripts" / f"relatorio_reimport_{ts}.csv"
    campos_csv = [
        "arquivo_origem", "ano", "mes", "complemento_provavel",
        "formato_detectado", "resultado",
        "agrupadoras_importadas", "faturas_importadas", "warnings", "erros",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos_csv)
        writer.writeheader()
        for linha in todas_linhas:
            writer.writerow({k: linha.get(k, "") for k in campos_csv})

    # ── Resumo terminal ──────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  REIMPORT HISTÓRICO — RESUMO")
    if args.dry_run:
        print("  [DRY-RUN: nada foi persistido]")
    print("=" * 60)
    print(f"  Anos processados : {anos_validos}")
    print(f"  Lotes detectados : {len(todas_linhas)}")
    print(f"  Erros            : {stats_globais['erros']}")
    if not args.dry_run:
        delta_ag  = n_depois - n_antes
        delta_fat = fat_depois - fat_antes
        sinal_ag  = f"+{delta_ag}"  if delta_ag  >= 0 else str(delta_ag)
        sinal_fat = f"+{delta_fat}" if delta_fat >= 0 else str(delta_fat)
        print(f"\n  ANTES:  {n_antes:>5} agrupadoras | {fat_antes:>6} faturas")
        print(f"  DEPOIS: {n_depois:>5} agrupadoras | {fat_depois:>6} faturas"
              f"  ({sinal_ag} agrupadoras, {sinal_fat} faturas)")
    print(f"\n  Relatório CSV: {csv_path}")
    if snap_antes_path:
        print(f"  Snapshot antes : {snap_antes_path}")
    if snap_depois_path:
        print(f"  Snapshot depois: {snap_depois_path}")
    print("=" * 60)

    # Por lote, imprime contagem de lotes por ano em dry-run
    if args.dry_run:
        print("\n  Lotes detectados por ano:")
        for ano in anos_validos:
            n_lotes_ano = sum(1 for l in todas_linhas if l.get("ano") == ano)
            print(f"    {ano}: {n_lotes_ano} lote(s)")


if __name__ == "__main__":
    main()
