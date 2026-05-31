"""
QThread worker que carrega tudo do banco de dados no inicio da UI.

Emite:
    iniciou(total)         — assim que detecta quantas agrupadoras tem
    item_carregado(item)   — cada agrupadora carregada (igual ao worker de processamento)
    concluido(n, tempo_ms) — carga terminou
    erro(msg)              — problema na conexao ou no carregamento
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class DbLoaderWorker(QThread):
    iniciou = Signal(int)
    item_carregado = Signal(object)
    concluido = Signal(int, int)      # (n, tempo_ms)
    erro = Signal(str)

    def __init__(self):
        super().__init__()

    def run(self):
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            from db.connection import get_session, testar_conexao
            from db.repository import carregar_itens_da_base
        except Exception as e:
            self.erro.emit(f"Falha ao importar modulos de banco: {e}")
            return

        t0 = time.time()

        try:
            testar_conexao()
        except Exception as e:
            self.erro.emit(
                f"Nao foi possivel conectar ao banco: {e}\n"
                "Rode 'python setup.py' e configure o .env para habilitar "
                "a carga automatica."
            )
            return

        session = get_session()
        try:
            itens = carregar_itens_da_base(session)
        except Exception as e:
            self.erro.emit(f"Erro ao ler agrupadoras: {e}")
            session.close()
            return

        self.iniciou.emit(len(itens))
        for it in itens:
            self.item_carregado.emit(it)

        session.close()
        ms = int((time.time() - t0) * 1000)
        self.concluido.emit(len(itens), ms)
