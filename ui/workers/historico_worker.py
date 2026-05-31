"""
Worker do "Importar acervo histórico" — paridade com o CLI `--modo historico`.

Varre uma pasta no estilo `FATURAS - SEMED/` e importa todo o acervo,
tratando os formatos antigos automaticamente (fragmentado → funde,
consolidado → divide, pasta mista → filtra), reusando exatamente as mesmas
funções do CLI: ingest.orquestrador.expandir_pasta_historica + main.processar_pdf.

É idempotente: documentos já no banco são pulados (dedup por documento), então
pode ser rodado de novo sem duplicar.

Emite:
    progresso(int, str)  — (nº de lotes processados, rótulo do último lote)
    log(str, str)        — (texto, nível) — espelha o log de ingest/parser
    concluido(dict)      — estatísticas finais
    banco_atualizado()   — após pelo menos 1 commit
"""
from __future__ import annotations

import logging
import sys
import shutil
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class _QtLogHandler(logging.Handler):
    """Encaminha registros de log para um signal Qt (thread-safe via queued)."""

    def __init__(self, emit_fn):
        super().__init__()
        self._emit = emit_fn

    def emit(self, record):
        try:
            msg = record.getMessage()
            if record.levelno >= logging.ERROR:
                nivel = "error"
            elif record.levelno >= logging.WARNING:
                nivel = "warn"
            else:
                nivel = "info"
            self._emit(msg, nivel)
        except Exception:
            pass


class HistoricoImportWorker(QThread):
    progresso = Signal(int, str)
    log = Signal(str, str)
    concluido = Signal(object)
    banco_atualizado = Signal()

    def __init__(self, raiz: Path):
        super().__init__()
        self._raiz = Path(raiz)
        self._cancel = False

    def cancelar(self):
        self._cancel = True
        self.requestInterruption()

    def _deve_cancelar(self) -> bool:
        return self._cancel or self.isInterruptionRequested()

    def run(self):
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        stats = {"lotes": 0, "agrupadoras": 0, "faturas": 0,
                 "duplicados": 0, "erros": 0}

        # Imports protegidos (componentes nativos podem faltar no cliente).
        try:
            from ingest.orquestrador import expandir_pasta_historica
            from main import processar_pdf, Stats
            from db.connection import get_session, testar_conexao
        except Exception as e:
            traceback.print_exc()
            self.log.emit(f"✗ Falha ao carregar componentes de importação: {e}", "error")
            self.concluido.emit(stats)
            return

        try:
            testar_conexao()
            session = get_session()
        except Exception as e:
            self.log.emit(f"✗ Banco indisponível: {e}", "error")
            self.concluido.emit(stats)
            return

        # Captura os logs de ingest/parser ("semed*") e joga na UI.
        semed_log = logging.getLogger("semed")
        nivel_anterior = semed_log.level
        handler = _QtLogHandler(lambda m, n: self.log.emit(m, n))
        handler.setLevel(logging.INFO)
        semed_log.addHandler(handler)
        semed_log.setLevel(logging.INFO)
        logger = logging.getLogger("semed.app.historico")

        destino = Path(tempfile.mkdtemp(prefix="semed_hist_"))
        houve_commit = False
        try:
            self.log.emit(f"Varrendo {self._raiz}…", "title")
            for lote in expandir_pasta_historica(self._raiz, destino):
                if self._deve_cancelar():
                    self.log.emit("⏹ Importação cancelada.", "warn")
                    break

                stats["lotes"] += 1
                pdf = lote.pdf_logico
                fontes = [str(a.caminho) for a in lote.arquivos_consumidos]
                origem = fontes[0] if fontes else (pdf.name if pdf else "?")
                rotulo = (f"{lote.ano}/{lote.mes:02d} {lote.complemento_provavel} "
                          f"[{lote.formato}]")

                if pdf is None or not pdf.exists():
                    stats["erros"] += 1
                    self.log.emit(f"✗ {rotulo}: sem PDF lógico", "error")
                    self.progresso.emit(stats["lotes"], rotulo)
                    continue

                st = Stats()
                try:
                    processar_pdf(pdf, session, st, logger,
                                  dry_run=False, mover=False,
                                  arquivo_origem_real=origem)
                    stats["agrupadoras"] += st.importados
                    stats["faturas"] += st.faturas_importadas
                    dup = st.duplicados_doc + st.duplicados_hash
                    stats["duplicados"] += dup
                    if st.importados:
                        houve_commit = True
                        self.log.emit(
                            f"✓ {rotulo}: importado ({st.faturas_importadas} faturas)",
                            "ok")
                    elif dup:
                        self.log.emit(f"— {rotulo}: já no banco (duplicado)", "info")
                    else:
                        self.log.emit(f"— {rotulo}: nada importado", "info")
                except Exception as e:
                    stats["erros"] += 1
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    self.log.emit(f"✗ {rotulo}: {e}", "error")

                self.progresso.emit(stats["lotes"], rotulo)
        except Exception as e:
            traceback.print_exc()
            self.log.emit(f"✗ Erro geral na importação do acervo: {e}", "error")
        finally:
            semed_log.removeHandler(handler)
            semed_log.setLevel(nivel_anterior)
            try:
                session.close()
            except Exception:
                pass
            shutil.rmtree(destino, ignore_errors=True)

        if houve_commit:
            self.banco_atualizado.emit()
        self.concluido.emit(stats)
