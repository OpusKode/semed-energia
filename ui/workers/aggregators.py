"""
Workers que movem as agregacoes pesadas do Dashboard e Agrupadoras
fora do thread principal da UI.

Motivacao:
- Com ~10k faturas, os `sum`, `sorted` e filtros do Dashboard e da pagina
  de Agrupadoras seguravam o thread principal por 100-500ms a cada
  mudanca de filtro, travando a UI.
- Os debounces (`QTimer`) em `dashboard_page` e `agrupadoras_page` ja
  amortecem o trigger, mas o trabalho em si continuava sincrono.
- Os workers aqui executam o trabalho em QThread e emitem um dict
  pronto-para-plotar via signal. O thread principal so faz UI update.

Cada worker e "one-shot" (criar, start, emitir, terminar) — mais simples
que filas persistentes. Se o usuario troca o filtro enquanto um worker
ainda roda, o chamador deve chamar `cancelar()` no anterior; o dict
emitido por worker cancelado e ignorado pelo `_finished` via flag.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal


# =============================================================
# Dashboard
# =============================================================

class DashboardAggregatorWorker(QThread):
    """Computa KPIs + dados dos 4 graficos do Dashboard.

    Output emitido em `pronto`:
        {
            "kpis": {"total_fat": int, "total_kwh": float,
                     "total_valor": float, "unidades": int},
            "top_unidades": [(nome, valor), ...],   # top 10, maior -> menor
            "tensao":       [(tensao, contagem), ...],  # maior -> menor
            "bairros":      [(bairro, kwh), ...],   # top 10, maior -> menor
            "distribuicao": {"centers": [...], "counts": [...],
                             "width": float, "min": float, "max": float},
        }
    """

    pronto = Signal(object)

    def __init__(
        self,
        dados: list[dict],
        filtro_doc: str | None,
        filtro_tensao: str | None = None,
        filtro_bairro: str | None = None,
        filtro_texto: str | None = None,
    ):
        super().__init__()
        # Copias rasas para nao depender de mutacoes na UI durante o run.
        self._dados = list(dados)
        self._filtro_doc = filtro_doc
        self._filtro_tensao = filtro_tensao
        self._filtro_bairro = filtro_bairro
        self._filtro_texto = (filtro_texto or "").strip().lower() or None
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        # ----- selecao -----
        if self._filtro_doc is None:
            itens = self._dados
        else:
            itens = [
                it for it in self._dados
                if it.get("capa", {}).get("documento") == self._filtro_doc
            ]

        todas_faturas: list[dict] = []
        for it in itens:
            todas_faturas.extend(it.get("faturas", []))

        # ----- Filtros adicionais por fatura -----
        if self._filtro_tensao:
            todas_faturas = [
                f for f in todas_faturas
                if (f.get("tensao") or "?") == self._filtro_tensao
            ]
        if self._filtro_bairro:
            alvo = self._filtro_bairro.strip().lower()
            todas_faturas = [
                f for f in todas_faturas
                if ((f.get("bairro") or "-").strip().lower()).startswith(alvo)
            ]
        if self._filtro_texto:
            termo = self._filtro_texto
            todas_faturas = [
                f for f in todas_faturas
                if termo in (f.get("nome_unidade") or "").lower()
                or termo in (f.get("bairro") or "").lower()
                or termo in str(f.get("instalacao") or "").lower()
            ]

        if self._cancelado:
            return

        # ----- KPIs -----
        total_fat = len(todas_faturas)
        total_kwh = sum(f.get("consumo_kwh", 0) or 0 for f in todas_faturas)
        total_valor = sum(f.get("valor", 0) or 0 for f in todas_faturas)
        unidades = len({
            f.get("instalacao") for f in todas_faturas if f.get("instalacao")
        })

        # ----- Top 10 unidades por valor -----
        top = sorted(todas_faturas, key=lambda f: -(f.get("valor") or 0))[:10]
        top_unidades = [
            (
                (f.get("nome_unidade") or "-")[:32],
                f.get("valor", 0) or 0,
                f.get("instalacao") or "",
            )
            for f in top
        ]

        if self._cancelado:
            return

        # ----- Tensao -----
        contagem: dict[str, int] = {}
        for f in todas_faturas:
            t = f.get("tensao") or "?"
            contagem[t] = contagem.get(t, 0) + 1
        tensao = sorted(contagem.items(), key=lambda x: -x[1])

        # ----- Bairros -----
        agr: dict[str, float] = {}
        for f in todas_faturas:
            b = (f.get("bairro") or "-").strip() or "-"
            agr[b] = agr.get(b, 0) + (f.get("consumo_kwh") or 0)
        bairros = sorted(agr.items(), key=lambda x: -x[1])[:10]
        bairros = [(b[:28], v) for b, v in bairros]

        if self._cancelado:
            return

        # ----- Distribuicao (histograma de valores) -----
        vals = [f.get("valor", 0) or 0 for f in todas_faturas]
        if vals:
            mn, mx = min(vals), max(vals)
            if mx <= mn:
                mx = mn + 1
            bins = 15
            width = (mx - mn) / bins
            counts = [0] * bins
            for v in vals:
                idx = min(int((v - mn) / width), bins - 1) if width > 0 else 0
                counts[idx] += 1
            edges = [mn + i * width for i in range(bins + 1)]
            centers = [(edges[i] + edges[i + 1]) / 2 for i in range(bins)]
            distribuicao = {
                "centers": centers, "counts": counts,
                "width": width, "min": mn, "max": mx,
            }
        else:
            distribuicao = {
                "centers": [], "counts": [], "width": 0, "min": 0, "max": 0,
            }

        if self._cancelado:
            return

        self.pronto.emit({
            "kpis": {
                "total_fat": total_fat, "total_kwh": total_kwh,
                "total_valor": total_valor, "unidades": unidades,
            },
            "top_unidades": top_unidades,
            "tensao": tensao,
            "bairros": bairros,
            "distribuicao": distribuicao,
        })


# =============================================================
# Agrupadoras (filtro textual)
# =============================================================

class AgrupadorasFilterWorker(QThread):
    """Aplica filtro textual sobre a lista de agrupadoras e devolve rows
    prontos para o `SimpleTableModel`.
    """

    pronto = Signal(object)  # list[dict] com rows

    def __init__(self, dados: list[dict], termo: str):
        super().__init__()
        self._dados = list(dados)
        self._termo = (termo or "").strip().lower()
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        termo = self._termo
        rows: list[dict] = []
        for it in self._dados:
            if self._cancelado:
                return
            capa = it.get("capa", {})
            if termo:
                blob = " ".join(str(v) for v in capa.values() if v).lower()
                if termo not in blob:
                    continue
            vs = it.get("validacao", {})
            if vs.get("erro", 0) > 0:
                status = "erro"
            elif vs.get("warn", 0) > 0:
                status = "warnings"
            else:
                status = "ok"
            rows.append({
                **capa,
                "faturas_extraidas": it.get("faturas_extraidas"),
                "status": status,
            })

        if self._cancelado:
            return

        self.pronto.emit(rows)


# =============================================================
# Helpers de granularidade (Fase 4)
# =============================================================

def _chave_periodo(ano: int, mes: int, granularidade: str) -> str:
    """Converte (ano, mês) para string de período conforme granularidade."""
    if granularidade == "trimestral":
        tri = (mes - 1) // 3 + 1
        return f"{ano:04d}-T{tri}"
    elif granularidade == "semestral":
        sem = (mes - 1) // 6 + 1
        return f"{ano:04d}-S{sem}"
    elif granularidade == "anual":
        return f"{ano:04d}"
    else:  # mensal (default)
        return f"{ano:04d}-{mes:02d}"


def _agregar_por_granularidade(
    dados: list[dict], granularidade: str,
) -> list[dict]:
    """Agrega lista de pontos mensais (dict com 'ano', 'mes', 'kwh', 'valor')
    para a granularidade alvo. Retorna lista ordenada por período."""
    grupos: dict[str, dict] = {}
    for d in dados:
        chave = _chave_periodo(d["ano"], d["mes"], granularidade)
        if chave not in grupos:
            grupos[chave] = {"kwh": 0.0, "valor": 0.0}
        grupos[chave]["kwh"] += d.get("kwh", 0.0)
        grupos[chave]["valor"] += d.get("valor", 0.0)
    return [
        {"periodo": k, "kwh": v["kwh"], "valor": v["valor"]}
        for k, v in sorted(grupos.items())
    ]


def _sys_path_root():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


# =============================================================
# Série histórica por complemento_norm (Fase 4.3)
# =============================================================

class SerieHistoricaWorker(QThread):
    """Busca série histórica agregada por complemento_norm via banco.

    Emite pronto(dict):
        {"series": {complemento_norm: [{"periodo": str, "kwh": float,
                                        "valor": float}, ...]}}

    Args:
        complementos: lista de complemento_norm a incluir; [] = todos.
        granularidade: "mensal" | "trimestral" | "semestral" | "anual".
        inicio: date | None — limite inferior (inclusive).
        fim:    date | None — limite superior (inclusive).
    """

    pronto = Signal(object)

    def __init__(
        self,
        complementos: list,
        granularidade: str = "mensal",
        inicio=None,
        fim=None,
    ):
        super().__init__()
        self._complementos = list(complementos)
        self._granularidade = granularidade
        self._inicio = inicio
        self._fim = fim
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        _sys_path_root()
        try:
            from db.connection import get_session, testar_conexao
            testar_conexao()
        except Exception:
            self.pronto.emit({"series": {}})
            return

        session = get_session()
        try:
            resultado = self._buscar(session)
        except Exception:
            resultado = {"series": {}}
        finally:
            session.close()

        if not self._cancelado:
            self.pronto.emit(resultado)

    def _buscar(self, session) -> dict:
        from sqlalchemy import text, bindparam

        filtros = ["fa.ano IS NOT NULL", "fa.mes IS NOT NULL"]
        params: dict = {}

        if self._complementos:
            # `IN :complementos` (expanding) funciona em SQLite e PostgreSQL.
            filtros.append("fa.complemento_norm IN :complementos")
            params["complementos"] = self._complementos

        if self._inicio:
            filtros.append(
                "(fa.ano > :ano_ini OR (fa.ano = :ano_ini AND fa.mes >= :mes_ini))"
            )
            params["ano_ini"] = self._inicio.year
            params["mes_ini"] = self._inicio.month

        if self._fim:
            filtros.append(
                "(fa.ano < :ano_fim OR (fa.ano = :ano_fim AND fa.mes <= :mes_fim))"
            )
            params["ano_fim"] = self._fim.year
            params["mes_fim"] = self._fim.month

        where = " AND ".join(filtros)
        sql = text(f"""
            WITH kwh_ag AS (
                SELECT agrupadora_id,
                       COALESCE(SUM(consumo_kwh), 0) AS total_kwh
                FROM fatura_individual
                GROUP BY agrupadora_id
            )
            SELECT
                fa.complemento_norm,
                fa.ano,
                fa.mes,
                COALESCE(k.total_kwh, 0)    AS kwh,
                COALESCE(fa.valor_total, 0) AS valor
            FROM fatura_agrupadora fa
            LEFT JOIN kwh_ag k ON k.agrupadora_id = fa.id
            WHERE {where}
            ORDER BY fa.complemento_norm, fa.ano, fa.mes
        """)
        if self._complementos:
            sql = sql.bindparams(bindparam("complementos", expanding=True))

        rows = session.execute(sql, params).fetchall()

        por_comp: dict = {}
        for row in rows:
            if self._cancelado:
                return {"series": {}}
            comp, ano, mes, kwh, valor = row
            comp = comp or "?"
            if comp not in por_comp:
                por_comp[comp] = []
            por_comp[comp].append({
                "ano": ano, "mes": mes,
                "kwh": float(kwh), "valor": float(valor),
            })

        series = {
            comp: _agregar_por_granularidade(dados, self._granularidade)
            for comp, dados in por_comp.items()
        }
        return {"series": series}


# =============================================================
# Decomposição de custo por período (Fase 4.3)
# =============================================================

class DecomposicaoWorker(QThread):
    """Agrega campos demo_* + multa/juros/correcao por período (stacked bar).

    Emite pronto(list[dict]):
        [{"periodo": str, "energia": float, "transmissao": float,
          "distribuicao": float, "enc_setoriais": float, "tributos": float,
          "multa_juros": float, "correcao": float}, ...]
    """

    pronto = Signal(object)

    def __init__(
        self,
        complementos: list,
        granularidade: str = "mensal",
        inicio=None,
        fim=None,
    ):
        super().__init__()
        self._complementos = list(complementos)
        self._granularidade = granularidade
        self._inicio = inicio
        self._fim = fim
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        _sys_path_root()
        try:
            from db.connection import get_session, testar_conexao
            testar_conexao()
        except Exception:
            self.pronto.emit([])
            return

        session = get_session()
        try:
            resultado = self._buscar(session)
        except Exception:
            resultado = []
        finally:
            session.close()

        if not self._cancelado:
            self.pronto.emit(resultado)

    def _buscar(self, session) -> list:
        from sqlalchemy import text, bindparam

        filtros = ["ano IS NOT NULL", "mes IS NOT NULL"]
        params: dict = {}

        if self._complementos:
            # `IN :complementos` (expanding) funciona em SQLite e PostgreSQL.
            filtros.append("complemento_norm IN :complementos")
            params["complementos"] = self._complementos

        if self._inicio:
            filtros.append(
                "(ano > :ano_ini OR (ano = :ano_ini AND mes >= :mes_ini))"
            )
            params["ano_ini"] = self._inicio.year
            params["mes_ini"] = self._inicio.month

        if self._fim:
            filtros.append(
                "(ano < :ano_fim OR (ano = :ano_fim AND mes <= :mes_fim))"
            )
            params["ano_fim"] = self._fim.year
            params["mes_fim"] = self._fim.month

        where = " AND ".join(filtros)
        sql = text(f"""
            SELECT
                ano, mes,
                COALESCE(SUM(demo_energia), 0)                              AS energia,
                COALESCE(SUM(demo_transmissao), 0)                          AS transmissao,
                COALESCE(SUM(demo_distribuicao), 0)                         AS distribuicao,
                COALESCE(SUM(demo_enc_setoriais), 0)                        AS enc_setoriais,
                COALESCE(SUM(demo_tributos), 0)                             AS tributos,
                COALESCE(SUM(COALESCE(multa, 0) + COALESCE(juros, 0)), 0)  AS multa_juros,
                COALESCE(SUM(correcao_monetaria), 0)                        AS correcao
            FROM fatura_agrupadora
            WHERE {where}
            GROUP BY ano, mes
            ORDER BY ano, mes
        """)
        if self._complementos:
            sql = sql.bindparams(bindparam("complementos", expanding=True))

        rows = session.execute(sql, params).fetchall()

        grupos: dict = {}
        for row in rows:
            if self._cancelado:
                return []
            ano, mes, eng, tra, dis, enc, tri, mul, cor = row
            chave = _chave_periodo(ano, mes, self._granularidade)
            if chave not in grupos:
                grupos[chave] = {
                    "energia": 0.0, "transmissao": 0.0,
                    "distribuicao": 0.0, "enc_setoriais": 0.0,
                    "tributos": 0.0, "multa_juros": 0.0, "correcao": 0.0,
                }
            g = grupos[chave]
            g["energia"] += float(eng)
            g["transmissao"] += float(tra)
            g["distribuicao"] += float(dis)
            g["enc_setoriais"] += float(enc)
            g["tributos"] += float(tri)
            g["multa_juros"] += float(mul)
            g["correcao"] += float(cor)

        return [{"periodo": k, **v} for k, v in sorted(grupos.items())]


# =============================================================
# Comparativo YoY (Fase 4.3)
# =============================================================

class YoYWorker(QThread):
    """Chama comparativo_anual do repository e emite os dados prontos.

    Emite pronto(dict):
        {ano: [{"mes": int, "valor": float}, ...]}
    """

    pronto = Signal(object)

    def __init__(self, complemento_norm: str, anos: list):
        super().__init__()
        self._complemento_norm = complemento_norm
        self._anos = list(anos)
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        _sys_path_root()
        try:
            from db.connection import get_session, testar_conexao
            from db.repository import comparativo_anual
            testar_conexao()
        except Exception:
            self.pronto.emit({})
            return

        session = get_session()
        try:
            resultado = comparativo_anual(
                session, self._complemento_norm, self._anos
            )
        except Exception:
            resultado = {}
        finally:
            session.close()

        if not self._cancelado:
            self.pronto.emit(resultado)


# =============================================================
# Cobertura histórica (Fase 5.4)
# =============================================================

class CoberturaWorker(QThread):
    """Consulta banco e emite matriz de cobertura mensal por agrupadora.

    Emite pronto(dict):
        {
            "complementos": ["SEMED-I", "SEMED-II", ...],
            "periodos":     ["2020-01", "2020-02", ...],
            "dados": {
                (complemento_norm, "AAAA-MM"): {
                    "valor_total": float,
                    "n_faturas":   int,
                }
            },
        }
    """

    pronto = Signal(object)

    def __init__(self):
        super().__init__()
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        _sys_path_root()
        try:
            from db.connection import get_session, testar_conexao
            testar_conexao()
        except Exception:
            self.pronto.emit({"complementos": [], "periodos": [], "dados": {}})
            return

        session = get_session()
        try:
            resultado = self._buscar(session)
        except Exception:
            resultado = {"complementos": [], "periodos": [], "dados": {}}
        finally:
            session.close()

        if not self._cancelado:
            self.pronto.emit(resultado)

    def _buscar(self, session) -> dict:
        from sqlalchemy import text

        sql = text("""
            SELECT
                complemento_norm,
                ano,
                mes,
                COALESCE(valor_total, 0)       AS valor_total,
                COALESCE(faturas_importadas, 0) AS n_faturas
            FROM fatura_agrupadora
            WHERE ano IS NOT NULL
              AND mes IS NOT NULL
              AND complemento_norm IS NOT NULL
            ORDER BY ano, mes, complemento_norm
        """)
        rows = session.execute(sql).fetchall()

        complementos_set: set[str] = set()
        periodos_set: set[str] = set()
        dados: dict = {}

        for comp, ano, mes, valor, n_fat in rows:
            if self._cancelado:
                return {"complementos": [], "periodos": [], "dados": {}}
            periodo = f"{ano:04d}-{mes:02d}"
            complementos_set.add(comp)
            periodos_set.add(periodo)
            dados[(comp, periodo)] = {
                "valor_total": float(valor),
                "n_faturas":   int(n_fat),
            }

        return {
            "complementos": sorted(complementos_set),
            "periodos":     sorted(periodos_set),
            "dados":        dados,
        }