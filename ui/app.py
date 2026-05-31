"""
Entry point da UI desktop do SEMED Energia.

Uso:
    python -m ui.app
    ou
    python ui/app.py
"""
import sys
from pathlib import Path

# Garantir que o root do projeto esta no sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon

from ui.main_window import MainWindow
from ui.theme import STYLESHEET


def _assets_dir() -> Path:
    """
    Pasta de assets, robusta em dev E no app empacotado (PyInstaller).

    No exe, NÃO dá para usar Path(__file__) (vira caminho relativo resolvido
    contra o diretório de trabalho — que num atalho do Menu Iniciar pode ser
    qualquer um). Os datas do spec colocam os ícones em <bundle>/ui/assets/,
    e o bundle fica em sys._MEIPASS.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "")) or Path(sys.executable).parent
        for cand in (base / "ui" / "assets", base / "assets", base):
            if (cand / "icon.ico").exists() or (cand / "icon.png").exists():
                return cand
        return base / "ui" / "assets"
    return Path(__file__).resolve().parent / "assets"


ASSETS = _assets_dir()
ICON_ICO = ASSETS / "icon.ico"
ICON_PNG = ASSETS / "icon.png"


def _melhor_icone() -> QIcon | None:
    """Prefere .ico (multi-resolucao Windows) com fallback para .png."""
    if ICON_ICO.exists():
        return QIcon(str(ICON_ICO))
    if ICON_PNG.exists():
        return QIcon(str(ICON_PNG))
    return None


def _instalar_tratador_global_de_erros() -> None:
    """
    Converte exceções não tratadas na thread da UI num diálogo + log, em vez
    de o programa fechar silenciosamente. Erros dentro dos workers (QThreads)
    já são tratados nos próprios workers; este hook cobre a thread principal e
    serve de rede de segurança/diagnóstico no cliente.
    """
    import traceback
    from datetime import datetime

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        texto = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(texto)
        arq = None
        try:
            from config import PASTA_LOGS
            PASTA_LOGS.mkdir(parents=True, exist_ok=True)
            arq = PASTA_LOGS / "erros_ui.log"
            with open(arq, "a", encoding="utf-8") as f:
                f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{texto}\n")
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle("Erro inesperado")
            box.setText("Ocorreu um erro inesperado, mas o programa continua aberto.")
            if arq:
                box.setInformativeText(f"Detalhes técnicos salvos em:\n{arq}")
            box.setDetailedText(texto[-4000:])
            box.exec()
        except Exception:
            pass

    sys.excepthook = _hook


def _checar_atualizacao() -> bool:
    """
    Executa o fluxo de auto-atualização COM janela de progresso
    (ui.update_flow): verifica → pergunta → baixa com barra → instala/reinicia.
    Retorna True se uma atualização foi aplicada (o app deve encerrar).

    Só roda no app empacotado; em desenvolvimento é pulado para não atrapalhar
    (defina SEMED_FORCE_UPDATE_CHECK=1 para forçar o teste do fluxo em dev).
    Nunca propaga exceções: falha de rede não impede o uso do app.
    """
    import os
    if not getattr(sys, "frozen", False) and not os.getenv("SEMED_FORCE_UPDATE_CHECK"):
        return False
    try:
        from ui.update_flow import executar_fluxo_update
        return executar_fluxo_update()
    except Exception:
        return False


# Mantém o arquivo do faulthandler aberto pela vida do processo.
_FH_FILE = None


def _ativar_faulthandler() -> None:
    """
    Captura crashes NATIVOS (segfault/abort em libs C como PyMuPDF/pdfplumber)
    em logs/crash_nativo.log. Exceções Python já vão para erros_ui.log; isto
    cobre o caso 'app fecha sem nenhum log'.
    """
    global _FH_FILE
    try:
        import faulthandler
        from datetime import datetime
        from config import PASTA_LOGS
        PASTA_LOGS.mkdir(parents=True, exist_ok=True)
        _FH_FILE = open(PASTA_LOGS / "crash_nativo.log", "a", encoding="utf-8")
        _FH_FILE.write(f"\n===== sessão {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        _FH_FILE.flush()
        faulthandler.enable(file=_FH_FILE)
    except Exception:
        pass


def _diag() -> int:
    """
    Modo diagnóstico headless (sem GUI): roda a leitura/parse de um PDF usando
    as MESMAS libs do app empacotado e grava um relatório em logs/diag.txt.
    Como o faulthandler está ativo, um crash nativo deixa o stack no relatório.

    Uso:  "SEMED Energia.exe" --diag "C:\\caminho\\fatura.pdf"
    """
    import traceback
    from datetime import datetime
    from pathlib import Path
    from config import PASTA_LOGS
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    rel = PASTA_LOGS / "diag.txt"
    fh = open(rel, "w", encoding="utf-8")

    def w(msg):
        fh.write(str(msg) + "\n")
        fh.flush()

    try:
        import faulthandler
        faulthandler.enable(file=fh)
        w(f"=== DIAG {datetime.now():%Y-%m-%d %H:%M:%S} ===")
        w(f"python: {sys.version}")
        w(f"frozen: {getattr(sys, 'frozen', False)}  _MEIPASS={getattr(sys, '_MEIPASS', None)}")
        import sqlite3
        w(f"sqlite: {sqlite3.sqlite_version}")
        w("import fitz...")
        import fitz
        w(f"  fitz OK (pymupdf {getattr(fitz, 'pymupdf_version', getattr(fitz, 'VersionBind', '?'))})")
        w("import pdfplumber...")
        import pdfplumber
        w("  pdfplumber OK")
        w("import parser...")
        from parser.classifier import classificar_pdf
        from parser.capa_parser import parsear_capa
        from parser.detalhe_parser import parsear_pagina_b3, parsear_pagina_a4
        w("  parser OK")

        pdfs = [a for a in sys.argv if a.lower().endswith(".pdf")]
        if not pdfs:
            w("Nenhum PDF passado (use --diag <arquivo.pdf>). Encerrando imports-only OK.")
            return 0
        pdf = Path(pdfs[0])
        w(f"PDF: {pdf}  existe={pdf.exists()}")
        w("fitz.open...")
        doc = fitz.open(str(pdf))
        w(f"  paginas={len(doc)}")
        w("classificar_pdf...")
        cls = classificar_pdf(pdf, doc=doc)
        w(f"  eh_equatorial={cls.eh_equatorial}  paginas={len(cls.paginas)}  erro={cls.erro}")
        w("parsear_capa...")
        capa = parsear_capa(pdf, doc=doc)
        doc.close()
        w(f"  capa doc={capa.documento}")
        w("pdfplumber parse B3/A4...")
        faturas = []
        with pdfplumber.open(str(pdf)) as po:
            for p in cls.paginas:
                if p.tipo == "detalhe_b3":
                    faturas += list(parsear_pagina_b3(po.pages[p.numero], p.numero))
                elif p.tipo == "detalhe_a4":
                    ff = parsear_pagina_a4(po.pages[p.numero], p.numero)
                    if ff:
                        faturas.append(ff)
        w(f"  faturas={len(faturas)}")
        w("DIAG OK")
        return 0
    except Exception:
        w("EXCEPTION:\n" + traceback.format_exc())
        return 2
    finally:
        try:
            fh.flush()
            fh.close()
        except Exception:
            pass


def _diag_ui() -> int:
    """
    Diagnóstico do caminho COMPLETO da GUI (janela + worker em QThread +
    atualização das páginas/gráficos), que o --diag headless não cobre.
    Dirige a importação de um PDF pela UploadPage real e grava logs/diag_ui.txt.
    Crash nativo (ex.: pyqtgraph) é capturado pelo faulthandler.

    Uso:  "SEMED Energia.exe" --diag-ui "C:\\caminho\\fatura.pdf"
    """
    import traceback
    from datetime import datetime
    from pathlib import Path
    from config import PASTA_LOGS
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    rel = PASTA_LOGS / "diag_ui.txt"
    fh = open(rel, "w", encoding="utf-8")

    def w(m):
        fh.write(str(m) + "\n")
        fh.flush()

    try:
        import faulthandler
        faulthandler.enable(file=fh)
        w(f"=== DIAG-UI {datetime.now():%H:%M:%S} ===")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        app = QApplication(sys.argv)
        w("QApplication OK")
        from db.connection import init_db
        init_db(); w("init_db OK")
        from ui.main_window import MainWindow
        win = MainWindow(); w("MainWindow criada")
        win.show(); w("show OK")

        pdfs = [a for a in sys.argv if a.lower().endswith(".pdf")]
        if not pdfs:
            w("sem PDF — abriu a janela OK (sem importar)")
            QTimer.singleShot(2000, app.quit)
            app.exec()
            w("DIAG-UI OK (sem import)")
            return 0

        up = win.upload_page
        up._add_files([Path(pdfs[0])]); w("PDF na fila")
        up._start(); w("worker iniciado")
        up.worker.concluido.connect(lambda s: w(f"worker concluido: {s}"))
        # Dá 4s após concluir para as páginas/gráficos atualizarem, depois fecha.
        up.worker.concluido.connect(lambda s: QTimer.singleShot(4000, app.quit))
        QTimer.singleShot(120000, app.quit)
        w("entrando no event loop...")
        app.exec()
        w("event loop terminou — DIAG-UI OK")
        return 0
    except Exception:
        w("EXCEPTION:\n" + traceback.format_exc())
        return 2
    finally:
        try:
            fh.flush(); fh.close()
        except Exception:
            pass


def _diag_ui_hist() -> int:
    """Diagnóstico do caminho do 'Importar acervo histórico' (worker + páginas)."""
    import traceback
    from datetime import datetime
    from pathlib import Path
    from config import PASTA_LOGS
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    rel = PASTA_LOGS / "diag_ui_hist.txt"
    fh = open(rel, "w", encoding="utf-8")

    def w(m):
        fh.write(str(m) + "\n"); fh.flush()

    try:
        import faulthandler
        faulthandler.enable(file=fh)
        w(f"=== DIAG-UI-HIST {datetime.now():%H:%M:%S} ===")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        app = QApplication(sys.argv)
        from db.connection import init_db
        init_db(); w("init_db OK")
        from ui.main_window import MainWindow
        win = MainWindow(); win.show(); w("MainWindow OK")
        # pasta = primeiro arg que existe como diretório
        pasta = None
        for a in sys.argv[1:]:
            if a != "--diag-ui-hist" and Path(a).is_dir():
                pasta = a
                break
        if not pasta:
            w("sem pasta — encerrando"); QTimer.singleShot(1500, app.quit); app.exec(); return 0
        w(f"pasta: {pasta}")
        up = win.upload_page
        up._start_historico(Path(pasta))
        up._hist_worker.concluido.connect(lambda s: w(f"historico concluido: {s}"))
        up._hist_worker.concluido.connect(lambda s: QTimer.singleShot(4000, app.quit))
        QTimer.singleShot(300000, app.quit)
        w("event loop...")
        app.exec()
        w("event loop terminou — DIAG-UI-HIST OK")
        return 0
    except Exception:
        w("EXCEPTION:\n" + traceback.format_exc()); return 2
    finally:
        try:
            fh.flush(); fh.close()
        except Exception:
            pass


def main():
    _ativar_faulthandler()
    if "--diag" in sys.argv:
        raise SystemExit(_diag())
    if "--diag-ui" in sys.argv:
        raise SystemExit(_diag_ui())
    if "--diag-ui-hist" in sys.argv:
        raise SystemExit(_diag_ui_hist())

    app = QApplication(sys.argv)
    app.setApplicationName("SEMED Energia")
    app.setOrganizationName("Prefeitura de Ananindeua")

    # Rede de segurança: erros inesperados na UI viram diálogo + log,
    # nunca um fechamento silencioso.
    _instalar_tratador_global_de_erros()

    # No Windows, define AppUserModelID — necessario para que o icone
    # aparecer corretamente na barra de tarefas (sem agrupar com python.exe).
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "prefeitura.ananindeua.semed.energia"
            )
        except Exception:
            pass

    icone = _melhor_icone()
    if icone is not None:
        app.setWindowIcon(icone)

    # Tipografia e tema global — aplicados antes de criar qualquer widget,
    # evitando que o Qt reaaplique o stylesheet retroativamente (o que
    # causava QTimer::start com intervalo negativo durante a inicializacao).
    f = QFont("Segoe UI", 10)
    app.setFont(f)
    app.setStyleSheet(STYLESHEET)

    # Verifica atualização antes de abrir a janela. Se uma atualização
    # for aplicada, o app encerra para o instalador trocar os arquivos.
    if _checar_atualizacao():
        return

    # Garante banco/pastas criados (primeira execução inclusive).
    try:
        from db.connection import init_db
        init_db()
    except Exception as e:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Erro ao iniciar o banco",
                             f"Não foi possível inicializar o banco de dados:\n{e}")
        return

    win = MainWindow()
    if icone is not None:
        win.setWindowIcon(icone)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
