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


ASSETS = Path(__file__).resolve().parent / "assets"
ICON_ICO = ASSETS / "icon.ico"
ICON_PNG = ASSETS / "icon.png"


def _melhor_icone() -> QIcon | None:
    """Prefere .ico (multi-resolucao Windows) com fallback para .png."""
    if ICON_ICO.exists():
        return QIcon(str(ICON_ICO))
    if ICON_PNG.exists():
        return QIcon(str(ICON_PNG))
    return None


def _checar_atualizacao() -> bool:
    """
    Verifica/baixa atualização no GitHub. Se houver, pergunta ao usuário e,
    se aceito, aplica e sinaliza que o app deve encerrar (retorna True).
    Nunca propaga exceções: falha de rede não impede o uso do app.
    """
    try:
        from PySide6.QtWidgets import QMessageBox
        import updater

        res = updater.verificar()
        if not res.disponivel or not res.zip_baixado:
            return False

        resp = QMessageBox.question(
            None,
            "Atualização disponível",
            f"Uma nova versão ({res.versao_remota}) está disponível.\n"
            f"Versão atual: {res.versao_local}.\n\n"
            "Deseja atualizar agora? O programa será reiniciado.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if resp != QMessageBox.Yes:
            return False
        return updater.aplicar_e_reiniciar(res.zip_baixado)
    except Exception:
        return False


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SEMED Energia")
    app.setOrganizationName("Prefeitura de Ananindeua")

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
