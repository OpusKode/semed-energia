"""Worker assíncrono que detecta anomalias nas faturas armazenadas no banco.

Regras implementadas
--------------------
1. Consumo anômalo    — fatura_individual.consumo_kwh > μ + 2σ da série da instalação
2. Demanda ultrapass. — fatura_agrupadora.demanda_ultra_qtd > 0
3. Reativo alto       — consumo_reat_exc_qtd > 5 % do consumo ativo (consumo_qtd)
4. Multa / juros      — fatura_agrupadora.multa > 0 ou juros > 0
5. Cobertura incom.   — faturas_importadas < qtd_faturas_esperada

Cada alerta emitido tem formato:
    {
        "severidade": "ERRO" | "AVISO" | "INFO",
        "mensagem": str,
        "tipo_nav": "instalacao" | "agrupadora" | None,
        "chave_nav": str | None,   # chave para navegação (instalacao ou documento)
    }
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class AnomalyDetectorWorker(QThread):
    """Detecta anomalias em todo o banco (ou filtradas por instalação).

    Args:
        instalacao: se fornecido, restringe regras per-instalação à instalação
                    informada; regras por agrupadora são filtradas às agrupadoras
                    que contêm a instalação.

    Signals:
        alerta(dict)  — emitido para cada anomalia encontrada.
        concluido()   — emitido ao terminar (mesmo sem anomalias).

    Usage::
        w = AnomalyDetectorWorker()           # toda a base
        w = AnomalyDetectorWorker("1234567")  # só esta instalação
        w.alerta.connect(minha_pagina.on_alerta)
        w.concluido.connect(minha_pagina.on_deteccao_concluida)
        w.start()
    """

    alerta = Signal(object)
    concluido = Signal()

    def __init__(self, instalacao: str | None = None) -> None:
        super().__init__()
        self._instalacao = instalacao
        self._cancelado = False

    def cancelar(self) -> None:
        self._cancelado = True

    # ------------------------------------------------------------------
    # Thread principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            from db.connection import get_session, testar_conexao
        except Exception:
            self.concluido.emit()
            return

        try:
            testar_conexao()
        except Exception:
            self.concluido.emit()
            return

        session = get_session()
        try:
            if not self._cancelado:
                self._detectar_consumo_anomalo(session)
            if not self._cancelado:
                self._detectar_demanda_ultrapassada(session)
            if not self._cancelado:
                self._detectar_reativo_alto(session)
            if not self._cancelado:
                self._detectar_multa_juros(session)
            if not self._cancelado:
                self._detectar_cobertura_incompleta(session)
        except Exception:
            pass
        finally:
            session.close()

        self.concluido.emit()

    # ------------------------------------------------------------------
    # Regra 1 — consumo anômalo (fatura_individual)
    # ------------------------------------------------------------------

    def _detectar_consumo_anomalo(self, session) -> None:
        from sqlalchemy import text

        filtro_inst = ""
        params: dict = {}
        if self._instalacao:
            filtro_inst = "AND fi.instalacao = :instalacao"
            params["instalacao"] = self._instalacao

        # Variância populacional: Var = E[x²] - E[x]². Evita STDDEV_POP (que
        # não existe no SQLite) e SQRT (que exige build com math functions).
        # A regra "x > média + 2σ" é, para x>média, equivalente a
        # (x-média)² > 4·Var; e ordenar por z-score (x-média)/σ é monotônico
        # em (x-média)²/Var (x>média). Resultados idênticos, sem raiz quadrada.
        variancia = (
            "(AVG(consumo_kwh * consumo_kwh) "
            "- AVG(consumo_kwh) * AVG(consumo_kwh))"
        )
        sql = text(f"""
            WITH stats AS (
                SELECT
                    instalacao,
                    MAX(nome_unidade)        AS nome_unidade,
                    AVG(consumo_kwh)         AS media,
                    {variancia}              AS variancia
                FROM fatura_individual
                WHERE consumo_kwh IS NOT NULL AND consumo_kwh > 0
                  AND instalacao IS NOT NULL
                GROUP BY instalacao
                HAVING COUNT(*) >= 3
                   AND {variancia} > 0
            ),
            anomalias AS (
                SELECT
                    fi.instalacao,
                    fi.nome_unidade,
                    fi.consumo_kwh,
                    s.media,
                    s.variancia,
                    ROW_NUMBER() OVER (
                        PARTITION BY fi.instalacao
                        ORDER BY fi.data_faturamento DESC NULLS LAST
                    ) AS rn
                FROM fatura_individual fi
                JOIN stats s ON fi.instalacao = s.instalacao
                WHERE fi.consumo_kwh > s.media
                  AND (fi.consumo_kwh - s.media) * (fi.consumo_kwh - s.media)
                      > 4 * s.variancia
                  {filtro_inst}
            )
            SELECT instalacao, nome_unidade, consumo_kwh, media, variancia
            FROM anomalias
            WHERE rn = 1
            ORDER BY (consumo_kwh - media) * (consumo_kwh - media)
                     / NULLIF(variancia, 0) DESC
            LIMIT 50
        """)

        rows = session.execute(sql, params).fetchall()
        for r in rows:
            if self._cancelado:
                return
            instalacao, nome, kwh, media, desvio = r
            pct = ((kwh - media) / media * 100) if media else 0
            self.alerta.emit({
                "severidade": "AVISO",
                "mensagem": (
                    f"Consumo {pct:.0f}% acima do padrão — "
                    f"{nome or instalacao} ({instalacao})"
                ),
                "tipo_nav": "instalacao",
                "chave_nav": str(instalacao),
            })

    # ------------------------------------------------------------------
    # Regra 2 — demanda ultrapassada (fatura_agrupadora)
    # ------------------------------------------------------------------

    def _detectar_demanda_ultrapassada(self, session) -> None:
        from sqlalchemy import text

        filtro_inst, params = self._filtro_agrupadora_por_instalacao()
        sql = text(f"""
            SELECT documento, complemento_norm, referencia,
                   demanda_ultra_qtd, demanda_ultra_valor
            FROM fatura_agrupadora fa
            WHERE demanda_ultra_qtd IS NOT NULL AND demanda_ultra_qtd > 0
              {filtro_inst}
            ORDER BY ano DESC NULLS LAST, mes DESC NULLS LAST
            LIMIT 30
        """)

        rows = session.execute(sql, params).fetchall()
        for r in rows:
            if self._cancelado:
                return
            doc, comp, ref, qtd, val = r
            val_fmt = (
                f"{float(val):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
                if val else str(qtd)
            )
            self.alerta.emit({
                "severidade": "AVISO",
                "mensagem": (
                    f"Demanda ultrapassada em {val_fmt} kW — "
                    f"{comp or doc} {ref or ''}"
                ).strip(),
                "tipo_nav": "agrupadora",
                "chave_nav": str(doc),
            })

    # ------------------------------------------------------------------
    # Regra 3 — reativo excedente > 5 % do consumo ativo
    # ------------------------------------------------------------------

    def _detectar_reativo_alto(self, session) -> None:
        from sqlalchemy import text

        filtro_inst, params = self._filtro_agrupadora_por_instalacao()
        sql = text(f"""
            SELECT documento, complemento_norm, referencia,
                   consumo_reat_exc_qtd, consumo_qtd
            FROM fatura_agrupadora fa
            WHERE consumo_reat_exc_qtd IS NOT NULL
              AND consumo_qtd IS NOT NULL AND consumo_qtd > 0
              AND consumo_reat_exc_qtd > 0.05 * consumo_qtd
              {filtro_inst}
            ORDER BY ano DESC NULLS LAST, mes DESC NULLS LAST
            LIMIT 30
        """)

        rows = session.execute(sql, params).fetchall()
        for r in rows:
            if self._cancelado:
                return
            doc, comp, ref, _reat, _ativo = r
            self.alerta.emit({
                "severidade": "INFO",
                "mensagem": (
                    f"Fator de potência baixo — {comp or doc} {ref or ''}"
                ).strip(),
                "tipo_nav": "agrupadora",
                "chave_nav": str(doc),
            })

    # ------------------------------------------------------------------
    # Regra 4 — multa ou juros presentes
    # ------------------------------------------------------------------

    def _detectar_multa_juros(self, session) -> None:
        from sqlalchemy import text

        filtro_inst, params = self._filtro_agrupadora_por_instalacao()
        sql = text(f"""
            SELECT documento, complemento_norm, referencia,
                   COALESCE(multa, 0) + COALESCE(juros, 0) AS total_penalidades
            FROM fatura_agrupadora fa
            WHERE (multa IS NOT NULL AND multa > 0)
               OR (juros IS NOT NULL AND juros > 0)
              {filtro_inst}
            ORDER BY ano DESC NULLS LAST, mes DESC NULLS LAST
            LIMIT 30
        """)

        rows = session.execute(sql, params).fetchall()
        for r in rows:
            if self._cancelado:
                return
            doc, comp, ref, total = r
            total_fmt = (
                f"{float(total):,.2f}"
                .replace(",", "X").replace(".", ",").replace("X", ".")
            )
            self.alerta.emit({
                "severidade": "ERRO",
                "mensagem": (
                    f"Pagamento em atraso: R$ {total_fmt} — "
                    f"{comp or doc} {ref or ''}"
                ).strip(),
                "tipo_nav": "agrupadora",
                "chave_nav": str(doc),
            })

    # ------------------------------------------------------------------
    # Regra 5 — cobertura incompleta
    # ------------------------------------------------------------------

    def _detectar_cobertura_incompleta(self, session) -> None:
        from sqlalchemy import text

        filtro_inst, params = self._filtro_agrupadora_por_instalacao()
        sql = text(f"""
            SELECT documento, complemento_norm, referencia,
                   faturas_importadas, qtd_faturas_esperada
            FROM fatura_agrupadora fa
            WHERE qtd_faturas_esperada IS NOT NULL
              AND faturas_importadas IS NOT NULL
              AND qtd_faturas_esperada > 0
              AND faturas_importadas < qtd_faturas_esperada
              {filtro_inst}
            ORDER BY ano DESC NULLS LAST, mes DESC NULLS LAST
            LIMIT 30
        """)

        rows = session.execute(sql, params).fetchall()
        for r in rows:
            if self._cancelado:
                return
            doc, comp, ref, importadas, esperadas = r
            self.alerta.emit({
                "severidade": "AVISO",
                "mensagem": (
                    f"Cobertura incompleta: {importadas}/{esperadas} — "
                    f"{comp or doc} {ref or ''}"
                ).strip(),
                "tipo_nav": "agrupadora",
                "chave_nav": str(doc),
            })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _filtro_agrupadora_por_instalacao(self) -> tuple[str, dict]:
        """Retorna (fragmento SQL, params) para filtrar agrupadoras pela instalação."""
        if not self._instalacao:
            return "", {}
        filtro = """
            AND EXISTS (
                SELECT 1 FROM fatura_individual fi2
                WHERE fi2.agrupadora_id = fa.id
                  AND fi2.instalacao = :instalacao
            )
        """
        return filtro, {"instalacao": self._instalacao}
