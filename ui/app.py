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


def main():
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
