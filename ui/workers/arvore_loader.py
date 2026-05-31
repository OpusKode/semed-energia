"""Worker que carrega a hierarquia Ano > Mês > Agrupadora do banco."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class ArvoreLoaderWorker(QThread):
    """Carrega a hierarquia Ano > Mês > Agrupadora do banco.

    Emite pronto(dict):
        {ano: {mes: [{"complemento_norm": str, "n_faturas": int,
                      "valor_total": float, "documento": str,
                      "referencia": str}, ...]}}

    Chaves de primeiro nível: inteiros (ano), ordenados desc.
    Chaves de segundo nível: inteiros (mês 1–12).
    Agrupadoras sem ano/mês são ignoradas.

    Usage::
        w = ArvoreLoaderWorker()
        w.pronto.connect(minha_pagina.on_arvore_pronta)
        w.erro.connect(minha_pagina.on_erro)
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
            from db.repository import listar_agrupadoras
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
            agrupadoras = listar_agrupadoras(session)
        except Exception as e:
            self.erro.emit(f"Erro ao carregar árvore: {e}")
            session.close()
            return

        hierarquia: dict[int, dict[int, list[dict]]] = {}

        for ag in agrupadoras:
            if self._cancelado:
                break
            ano = ag.ano
            mes = ag.mes
            if ano is None or mes is None:
                continue
            if ano not in hierarquia:
                hierarquia[ano] = {}
            if mes not in hierarquia[ano]:
                hierarquia[ano][mes] = []
            hierarquia[ano][mes].append({
                "complemento_norm": ag.complemento_norm or "?",
                "n_faturas": ag.faturas_importadas or 0,
                "valor_total": float(ag.valor_total) if ag.valor_total else 0.0,
                "documento": ag.documento or "",
                "referencia": ag.referencia or "",
            })

        session.close()

        if not self._cancelado:
            self.pronto.emit(hierarquia)
