"""Worker que lista todas as instalações distintas do banco com metadados."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class InstalacaoLoaderWorker(QThread):
    """Lista todas as instalações distintas do banco com metadados.

    Emite pronto(list[dict]):
        [{"instalacao": str, "nome_unidade": str, "n_faturas": int}, ...]

    Ordenado por nome_unidade (NULLS LAST) depois instalacao.

    Usage::
        w = InstalacaoLoaderWorker()
        w.pronto.connect(minha_pagina.on_instalacoes_prontas)
        w.start()
    """

    pronto = Signal(object)
    erro = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancelado = False

    def cancelar(self) -> None:
        self._cancelado = True

    def run(self) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            from db.connection import get_session, testar_conexao
        except Exception as e:
            self.erro.emit(f"Falha ao importar módulos de banco: {e}")
            return

        try:
            testar_conexao()
        except Exception as e:
            self.erro.emit(f"Banco offline: {e}")
            return

        session = get_session()
        try:
            from sqlalchemy import text

            sql = text("""
                SELECT
                    instalacao,
                    MAX(nome_unidade) AS nome_unidade,
                    COUNT(*)          AS n_faturas
                FROM fatura_individual
                WHERE instalacao IS NOT NULL
                GROUP BY instalacao
                ORDER BY MAX(nome_unidade) NULLS LAST, instalacao
            """)
            rows = session.execute(sql).fetchall()
        except Exception as e:
            self.erro.emit(f"Erro ao listar instalações: {e}")
            session.close()
            return

        session.close()

        if self._cancelado:
            return

        resultado = [
            {
                "instalacao": str(r[0]),
                "nome_unidade": r[1] or "",
                "n_faturas": int(r[2]),
            }
            for r in rows
        ]
        self.pronto.emit(resultado)
