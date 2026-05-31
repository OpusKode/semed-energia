"""
Workers QThread para exportar o banco sem travar a UI.

* ExportPowerBIWorker  - gera .xlsx com views modelo-estrela (Power BI).
* ExportRawWorker      - gera CSVs (um por tabela) ou um .xlsx bruto.
"""
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class ExportPowerBIWorker(QThread):
    progresso = Signal(int, int, str)
    concluido = Signal(object)
    erro = Signal(str)

    def __init__(self, destino: Path):
        super().__init__()
        self.destino = Path(destino)

    def run(self):
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            from db.connection import get_session, testar_conexao
            from export.powerbi import exportar_para_excel
        except Exception as e:
            self.erro.emit(f"Falha ao importar modulos: {e}")
            return

        try:
            testar_conexao()
        except Exception as e:
            self.erro.emit(
                f"Banco indisponivel: {e}\nConfigure o .env e rode setup.py."
            )
            return

        session = get_session()
        try:
            def _on_prog(i: int, total: int, nome: str):
                self.progresso.emit(i, total, nome)

            stats = exportar_para_excel(self.destino, session, on_progress=_on_prog)
            self.concluido.emit(stats)
        except Exception as e:
            traceback.print_exc()
            self.erro.emit(f"Erro na exportacao: {e}")
        finally:
            session.close()


class ExportRawWorker(QThread):
    """Worker para export bruto (CSV por tabela ou XLSX unico)."""

    progresso = Signal(int, int, str)
    concluido = Signal(object)
    erro = Signal(str)

    def __init__(self, destino: Path):
        super().__init__()
        self.destino = Path(destino)

    def run(self):
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            from db.connection import get_session, testar_conexao
            from export.raw import exportar_csv, exportar_xlsx_raw
        except Exception as e:
            self.erro.emit(f"Falha ao importar modulos: {e}")
            return

        try:
            testar_conexao()
        except Exception as e:
            self.erro.emit(
                f"Banco indisponivel: {e}\nConfigure o .env e rode setup.py."
            )
            return

        session = get_session()
        try:
            def _on_prog(i: int, total: int, nome: str):
                self.progresso.emit(i, total, nome)

            if self.destino.suffix.lower() == ".xlsx":
                stats = exportar_xlsx_raw(self.destino, session, on_progress=_on_prog)
                stats["modo"] = "xlsx"
            else:
                stats = exportar_csv(self.destino, session, on_progress=_on_prog)
                stats["modo"] = "csv"
            self.concluido.emit(stats)
        except Exception as e:
            traceback.print_exc()
            self.erro.emit(f"Erro na exportacao bruta: {e}")
        finally:
            session.close()
