"""
Camada de persistencia: mapeia as dataclasses dos parsers para os modelos
SQLAlchemy e grava tudo no banco (SQLite por padrao; PostgreSQL via override).

API publica:
    salvar_agrupadora(session, dados_capa, arquivo_origem) -> FaturaAgrupadora
    salvar_fatura_individual(session, agrupadora_id, fatura) -> FaturaIndividual
    registrar_arquivo(session, ...) -> ArquivoProcessado
    reprocessar_documento(session, documento) -> bool
    listar_anos(session) -> list[int]
    listar_meses_do_ano(session, ano) -> list[int]
    listar_agrupadoras(session, ano, mes, complemento_norm) -> list[FaturaAgrupadora]
    buscar_global(session, termo) -> list[FaturaAgrupadora]
    serie_temporal_unidade(session, instalacao, granularidade, inicio, fim) -> list[dict]
    comparativo_anual(session, complemento_norm, anos) -> dict[int, list[dict]]
"""
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session

from db.models import (
    ArquivoProcessado, FaturaAgrupadora, FaturaIndividual,
    Tributo, ValorFaturado, ValorMedido,
)


# =============================================================
# Derivação de campos temporais
# =============================================================

# Sufixos reconhecidos em complemento — mapeados para romano canônico.
_SEMED_SUFIXO = re.compile(
    r"SEMED[\s\-]*([1-4IVX]+)\s*$",
    re.IGNORECASE,
)
_NUMERAL_PARA_ROMANO = {"1": "I", "2": "II", "3": "III", "4": "IV"}
_ROMANO_VALIDOS = {"I", "II", "III", "IV"}


def _normalizar_complemento(complemento: str | None) -> str:
    """
    Converte variações livres de complemento para a forma canônica "SEMED-{romano}".

    Exemplos:
        "SEMED I"    → "SEMED-I"
        "SEMED-IV"   → "SEMED-IV"
        "SEMED 4"    → "SEMED-IV"
        "SEMED4"     → "SEMED-IV"
        "SEMED II"   → "SEMED-II"
        None         → "SEMED-?"
    """
    if not complemento:
        return "SEMED-?"
    m = _SEMED_SUFIXO.search(complemento.strip())
    if not m:
        return "SEMED-?"
    sufixo = m.group(1).upper().strip()
    romano = _NUMERAL_PARA_ROMANO.get(sufixo, sufixo)
    if romano not in _ROMANO_VALIDOS:
        return "SEMED-?"
    return f"SEMED-{romano}"


def _derivar_temporal(capa) -> tuple[int | None, int | None, str | None]:
    """
    Extrai (ano, mes, complemento_norm) de DadosCapa.

    `capa.referencia` tem formato "MM/AAAA" (ex.: "01/2026").
    `capa.complemento` tem variações livres ("SEMED I", "SEMED-IV", "SEMED 4", etc.).

    Retorna (None, None, None) se referencia for None ou não parseável.
    complemento_norm é sempre derivado mesmo que referencia falhe.
    """
    ano: int | None = None
    mes: int | None = None
    referencia = getattr(capa, "referencia", None)
    if referencia and "/" in referencia:
        partes = referencia.split("/")
        if len(partes) == 2:
            try:
                mes = int(partes[0])
                ano = int(partes[1])
            except ValueError:
                pass
    complemento_norm = _normalizar_complemento(getattr(capa, "complemento", None))
    return ano, mes, complemento_norm


# =============================================================
# Conversao DadosCapa -> FaturaAgrupadora
# =============================================================

# Campos da DadosCapa que mapeiam diretamente para FaturaAgrupadora.
# Ambos usam exatamente os mesmos nomes.
_CAMPOS_AGRUPADORA = [
    "documento", "referencia", "complemento", "conta_contrato",
    "cliente_cnpj", "parceiro_negocio",
    "emissao", "apresentacao", "vencimento",
    "valor_total", "qtd_faturas_esperada",
    "consumo_qtd", "consumo_valor",
    "consumo_ponta_qtd", "consumo_ponta_valor",
    "consumo_fp_qtd", "consumo_fp_valor",
    "demanda_ativa_qtd", "demanda_ativa_valor",
    "demanda_ultra_qtd", "demanda_ultra_valor",
    "consumo_reat_exc_qtd", "consumo_reat_exc_valor",
    "consumo_reat_exc_np_qtd", "consumo_reat_exc_np_valor",
    "consumo_reat_exc_fp_qtd", "consumo_reat_exc_fp_valor",
    "adicional_bandeira", "icms_total", "cofins_total", "pis_total",
    "subtotal_1",
    "trib_reter_irpj", "trib_reter_pis", "trib_reter_cofins",
    "trib_reter_csll", "credito_dic_fic_dmic", "cip_ilum_pub",
    "subtotal_2",
    "demo_energia", "demo_transmissao", "demo_distribuicao",
    "demo_enc_setoriais", "demo_tributos", "demo_soma",
    "icms_base_calculo", "icms_aliquota", "icms_valor",
    # Campos históricos (Fase 2) — ver migration 004_campos_historicos.sql
    # Mapeiam diretamente DadosCapa → FaturaAgrupadora (mesmo nome nos dois).
    # Se o campo for None em DadosCapa, é gravado como NULL no banco (não 0).
    "bandeira_amarela", "bandeira_vermelha",
    "correcao_monetaria", "multa", "juros",
    "devolucao_icms_lc194", "diferenca_bandeira",
    "versao_layout",
]


def salvar_agrupadora(
    session: Session,
    capa,
    arquivo_origem: str | None = None,
    cliente_nome: str | None = None,
) -> FaturaAgrupadora:
    """Cria e grava uma FaturaAgrupadora a partir de DadosCapa."""
    kwargs = {}
    for campo in _CAMPOS_AGRUPADORA:
        kwargs[campo] = getattr(capa, campo, None)

    ano, mes, complemento_norm = _derivar_temporal(capa)

    ag = FaturaAgrupadora(
        **kwargs,
        ano=ano,
        mes=mes,
        complemento_norm=complemento_norm,
        cliente_nome=cliente_nome or "PREFEITURA DE ANANINDEUA",
        status="pendente",
        faturas_importadas=0,
        faturas_com_erro=0,
        arquivo_origem=arquivo_origem,
        importado_em=datetime.now(),
    )
    session.add(ag)
    session.flush()
    return ag


# =============================================================
# Conversao DadosFaturaDetalhe -> FaturaIndividual + filhos
# =============================================================

_CAMPOS_FATURA = [
    "nota_fiscal", "fatura_numero", "instalacao", "nome_unidade",
    "endereco", "bairro", "municipio", "unidade_leitura", "conj_contrato",
    "classe_principal", "classe_consumo", "tensao", "fase",
    "data_faturamento", "dias_faturamento",
    "data_leitura_anterior", "data_leitura_atual",
    "hash_code", "data_apresentacao", "data_vencimento",
    "data_recolhimento", "valor",
]


def salvar_fatura_individual(
    session: Session,
    agrupadora_id: int,
    fatura,
) -> FaturaIndividual:
    """Grava FaturaIndividual + Tributos + ValoresFaturados + ValoresMedidos.

    Rejeita explicitamente `nota_fiscal` vazio/None: o DDL tem UNIQUE em
    `nota_fiscal`, mas SQL permite multiplos NULLs na mesma coluna UNIQUE —
    o que quebra silenciosamente a dedup C3 (duas faturas sem NF conseguiriam
    entrar). Falhar cedo aqui e mais seguro que tolerar inconsistencia.
    """
    nf = getattr(fatura, "nota_fiscal", None)
    if nf is None or (isinstance(nf, str) and not nf.strip()):
        raise ValueError(
            "nota_fiscal obrigatoria para persistir FaturaIndividual "
            f"(agrupadora_id={agrupadora_id}, instalacao="
            f"{getattr(fatura, 'instalacao', None)!r})"
        )

    kwargs = {c: getattr(fatura, c, None) for c in _CAMPOS_FATURA}

    # Persistimos `consumo_kwh` (soma dos `valor_faturado` cuja descricao
    # comeca com "Consumo") para evitar recomputar isso a cada carga da UI.
    # Vide migracao 003_consumo_kwh.sql.
    consumo_kwh = sum(
        (v.quantidade or 0) for v in getattr(fatura, "valores_faturados", [])
        if getattr(v, "descricao", None)
        and v.descricao.startswith("Consumo")
    )

    fi = FaturaIndividual(
        agrupadora_id=agrupadora_id,
        importado_em=datetime.now(),
        consumo_kwh=consumo_kwh,
        **kwargs,
    )
    session.add(fi)
    session.flush()

    for t in fatura.tributos:
        session.add(Tributo(
            fatura_individual_id=fi.id,
            tipo=t.tipo,
            base_calculo=t.base_calculo,
            aliquota=t.aliquota,
            valor=t.valor,
        ))

    for v in fatura.valores_faturados:
        session.add(ValorFaturado(
            fatura_individual_id=fi.id,
            descricao=v.descricao,
            quantidade=v.quantidade,
            preco=v.preco,
            valor=v.valor,
        ))

    for v in fatura.valores_medidos:
        session.add(ValorMedido(
            fatura_individual_id=fi.id,
            especie=v.especie,
            medidor=v.medidor,
            constante=v.constante,
            perc_fp=v.perc_fp,
            leitura_anterior=v.leitura_anterior,
            leitura_atual=v.leitura_atual,
            medido=v.medido,
            faturado=v.faturado,
        ))

    session.flush()
    return fi


# =============================================================
# Arquivo processado (controle de dedup)
# =============================================================

def registrar_arquivo(
    session: Session,
    nome_original: str,
    hash_sha256: str,
    resultado: str,
    tamanho_bytes: int | None = None,
    documento: str | None = None,
    agrupadora_id: int | None = None,
    nome_padronizado: str | None = None,
) -> ArquivoProcessado:
    """
    Insere registro em arquivo_processado.
    resultado: 'importado' | 'duplicado_hash' | 'duplicado_doc' | 'erro'
    """
    arq = ArquivoProcessado(
        nome_original=nome_original,
        nome_padronizado=nome_padronizado,
        hash_sha256=hash_sha256,
        tamanho_bytes=tamanho_bytes,
        documento=documento,
        agrupadora_id=agrupadora_id,
        processado_em=datetime.now(),
        resultado=resultado,
    )
    session.add(arq)
    session.flush()
    return arq


def atualizar_status_agrupadora(
    session: Session,
    agrupadora_id: int,
    status: str,
    faturas_importadas: int,
    faturas_com_erro: int,
    erros_log: str | None = None,
) -> None:
    ag = session.query(FaturaAgrupadora).filter_by(id=agrupadora_id).first()
    if ag is None:
        return
    ag.status = status
    ag.faturas_importadas = faturas_importadas
    ag.faturas_com_erro = faturas_com_erro
    ag.atualizado_em = datetime.now()
    if erros_log:
        ag.erros_log = erros_log
    session.flush()


# =============================================================
# Reprocessamento (delete-write)
# =============================================================

def reprocessar_documento(session: Session, documento: str) -> bool:
    """
    Remove agrupadora (CASCADE deleta faturas e filhos) e o registro em
    arquivo_processado. Caller fica responsavel pela reimportacao.
    """
    ag = session.query(FaturaAgrupadora).filter_by(documento=documento).first()
    if ag is None:
        return False
    session.delete(ag)
    session.flush()
    session.query(ArquivoProcessado).filter_by(documento=documento).delete()
    session.flush()
    return True


# =============================================================
# Carga em massa para a UI
# =============================================================

def _f(v):
    """Decimal/None -> float/None."""
    return float(v) if v is not None else None


def _fatura_to_dict(f: FaturaIndividual) -> dict:
    """Converte FaturaIndividual (e filhos) no mesmo formato que o worker emite."""
    # `consumo_kwh` e persistido na coluna (migracao 003). Fallback para a soma
    # em memoria caso o registro ainda nao tenha sido backfillado.
    if f.consumo_kwh is not None:
        consumo_kwh = float(f.consumo_kwh)
    else:
        consumo_kwh = sum(
            float(v.quantidade or 0) for v in f.valores_faturados
            if v.descricao and v.descricao.startswith("Consumo")
        )
    return {
        "nota_fiscal": f.nota_fiscal,
        "fatura_numero": f.fatura_numero,
        "instalacao": f.instalacao,
        "nome_unidade": f.nome_unidade,
        "endereco": f.endereco,
        "bairro": f.bairro,
        "municipio": f.municipio,
        "unidade_leitura": f.unidade_leitura,
        "conj_contrato": f.conj_contrato,
        "classe_principal": f.classe_principal,
        "classe_consumo": f.classe_consumo,
        "tensao": f.tensao,
        "fase": _f(f.fase),
        "data_faturamento": str(f.data_faturamento) if f.data_faturamento else "",
        "dias_faturamento": f.dias_faturamento,
        "data_leitura_anterior": str(f.data_leitura_anterior) if f.data_leitura_anterior else "",
        "data_leitura_atual": str(f.data_leitura_atual) if f.data_leitura_atual else "",
        "data_apresentacao": str(f.data_apresentacao) if f.data_apresentacao else "",
        "data_vencimento": str(f.data_vencimento) if f.data_vencimento else "",
        "data_recolhimento": str(f.data_recolhimento) if f.data_recolhimento else "",
        "hash_code": f.hash_code,
        "valor": _f(f.valor) or 0,
        "dias": f.dias_faturamento,
        "data_leitura": str(f.data_leitura_atual) if f.data_leitura_atual else "",
        "consumo_kwh": consumo_kwh,
        "tributos": [
            {"tipo": t.tipo, "base_calculo": _f(t.base_calculo),
             "aliquota": _f(t.aliquota), "valor": _f(t.valor)}
            for t in f.tributos
        ],
        "valores_faturados": [
            {"descricao": v.descricao, "quantidade": _f(v.quantidade),
             "preco": _f(v.preco), "valor": _f(v.valor)}
            for v in f.valores_faturados
        ],
        "valores_medidos": [
            {"especie": v.especie, "medidor": v.medidor,
             "constante": _f(v.constante), "perc_fp": _f(v.perc_fp),
             "leitura_anterior": _f(v.leitura_anterior),
             "leitura_atual": _f(v.leitura_atual),
             "medido": _f(v.medido), "faturado": _f(v.faturado)}
            for v in f.valores_medidos
        ],
    }


def carregar_itens_da_base(
    session: Session,
    limite: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """
    Le agrupadoras do banco e retorna uma lista no formato esperado
    pela UI (mesma estrutura que o worker emite em arquivo_concluido).

    Ordenado por referencia decrescente.

    Args:
        session: sessao SQLAlchemy aberta.
        limite: numero maximo de agrupadoras a carregar. `None` = todas
            (backward-compat). Use para paginar em bases grandes
            (ex.: 10k agrupadoras x 100 faturas = 1M linhas em RAM).
        offset: deslocamento para pagina atual.

    Usa `selectinload` em vez de `joinedload`: para relacionamentos 1-many
    o `joinedload` produz um cartesiano gigante (uma linha por combinacao
    de filhos), enquanto `selectinload` emite uma query extra por
    relacionamento com `WHERE parent_id IN (...)` — escala muito melhor.
    """
    from sqlalchemy.orm import selectinload

    q = (
        session.query(FaturaAgrupadora)
        .options(
            selectinload(FaturaAgrupadora.faturas)
            .selectinload(FaturaIndividual.tributos),
            selectinload(FaturaAgrupadora.faturas)
            .selectinload(FaturaIndividual.valores_faturados),
            selectinload(FaturaAgrupadora.faturas)
            .selectinload(FaturaIndividual.valores_medidos),
        )
        .order_by(
            FaturaAgrupadora.ano.desc().nulls_last(),
            FaturaAgrupadora.mes.desc().nulls_last(),
            FaturaAgrupadora.complemento_norm.asc().nulls_last(),
        )
    )

    if offset:
        q = q.offset(offset)
    if limite is not None:
        q = q.limit(limite)

    agrupadoras = q.all()

    itens = []
    for ag in agrupadoras:
        faturas = [_fatura_to_dict(f) for f in ag.faturas]
        item = {
            "pdf": ag.arquivo_origem or f"{ag.complemento or 'SEMED'}.pdf",
            "hash": "",
            "capa": {
                "documento": ag.documento,
                "complemento": ag.complemento,
                "referencia": ag.referencia,
                "conta_contrato": ag.conta_contrato,
                "valor_total": _f(ag.valor_total) or 0,
                "qtd_esperada": ag.qtd_faturas_esperada,
            },
            "faturas_extraidas": len(faturas),
            # Validacao nao e re-rodada no load; consideramos o status persistido.
            "validacao": {
                "ok": (ag.faturas_importadas or 0) * 3,  # aproximado
                "warn": 0,
                "erro": (ag.faturas_com_erro or 0),
                "total": 0,
                "por_camada": {1: 0, 2: 0, 3: 0},
            },
            "warnings": [],
            "erros": [],
            "faturas": faturas,
        }
        itens.append(item)

    return itens


def contar_agrupadoras(session: Session) -> int:
    """Retorna a contagem total de agrupadoras (para paginacao na UI)."""
    return session.query(FaturaAgrupadora.id).count()


# =============================================================
# Consultas hierárquicas (Fase 3)
# =============================================================

def listar_anos(session: Session) -> list[int]:
    """Anos com pelo menos 1 agrupadora. Ordenado decrescente."""
    rows = (
        session.query(FaturaAgrupadora.ano)
        .filter(FaturaAgrupadora.ano.isnot(None))
        .distinct()
        .order_by(FaturaAgrupadora.ano.desc())
        .all()
    )
    return [r[0] for r in rows]


def listar_meses_do_ano(session: Session, ano: int) -> list[int]:
    """Meses com pelo menos 1 agrupadora no ano dado. Ordenado crescente."""
    rows = (
        session.query(FaturaAgrupadora.mes)
        .filter(
            FaturaAgrupadora.ano == ano,
            FaturaAgrupadora.mes.isnot(None),
        )
        .distinct()
        .order_by(FaturaAgrupadora.mes.asc())
        .all()
    )
    return [r[0] for r in rows]


def listar_agrupadoras(
    session: Session,
    ano: int | None = None,
    mes: int | None = None,
    complemento_norm: str | None = None,
) -> list[FaturaAgrupadora]:
    """
    Filtro hierárquico por ano, mês e/ou complemento_norm.

    Args:
        ano: filtra pelo ano; None = todos os anos.
        mes: filtra pelo mês; None = todos os meses (só faz sentido com ano).
        complemento_norm: filtra pela forma canônica ("SEMED-I", etc.); None = todas.

    Retorna registros ordenados por (ano desc nulls last, mes desc nulls last,
    complemento_norm asc nulls last). Não carrega faturas filhas (lazy load).
    """
    q = session.query(FaturaAgrupadora)
    if ano is not None:
        q = q.filter(FaturaAgrupadora.ano == ano)
    if mes is not None:
        q = q.filter(FaturaAgrupadora.mes == mes)
    if complemento_norm is not None:
        q = q.filter(FaturaAgrupadora.complemento_norm == complemento_norm)
    return q.order_by(
        FaturaAgrupadora.ano.desc().nulls_last(),
        FaturaAgrupadora.mes.desc().nulls_last(),
        FaturaAgrupadora.complemento_norm.asc().nulls_last(),
    ).all()


def buscar_global(session: Session, termo: str) -> list[FaturaAgrupadora]:
    """
    Busca case-insensitive por `termo` em documento, complemento_norm e
    conta_contrato. Retorna até 200 resultados ordenados por (ano desc, mes desc).

    Usa ILIKE em PostgreSQL; em SQLite (testes) cai para LIKE (ASCII case-insensitive).
    """
    padrao = f"%{termo}%"
    q = (
        session.query(FaturaAgrupadora)
        .filter(
            FaturaAgrupadora.documento.ilike(padrao)
            | FaturaAgrupadora.complemento_norm.ilike(padrao)
            | FaturaAgrupadora.conta_contrato.ilike(padrao)
        )
        .order_by(
            FaturaAgrupadora.ano.desc().nulls_last(),
            FaturaAgrupadora.mes.desc().nulls_last(),
        )
        .limit(200)
    )
    return q.all()


def serie_temporal_unidade(
    session: Session,
    instalacao: str,
    granularidade: str = "mensal",
    inicio: date | None = None,
    fim: date | None = None,
) -> list[dict]:
    """
    Agrega kWh e R$ de fatura_individual para uma instalação ao longo do tempo.

    Args:
        instalacao: código da instalação (campo fatura_individual.instalacao).
        granularidade: "mensal" | "trimestral" | "semestral" | "anual".
        inicio: data mínima de data_faturamento (inclusive). None = sem limite.
        fim: data máxima de data_faturamento (inclusive). None = sem limite.

    Retorna lista de dicts {"periodo": str, "kwh": float, "valor": float, "n_faturas": int}
    ordenada cronologicamente. Usa SQL agregado (GROUP BY) no banco.

    A expressão de período é montada conforme o dialeto do banco: SQLite
    (padrão de produção) usa strftime/ceil; PostgreSQL (override de dev via
    SEMED_DB_URL) usa TO_CHAR/EXTRACT/CEIL.
    """
    dialeto = session.get_bind().dialect.name

    # Expressão de período por granularidade, por dialeto.
    if dialeto == "sqlite":
        # Trimestre/semestre via divisão inteira ((mes+2)/3, (mes+5)/6) —
        # idêntico a ceil(mes/3.0)/ceil(mes/6.0) porém sem depender das
        # funções matemáticas do SQLite (que exigem build com
        # SQLITE_ENABLE_MATH_FUNCTIONS). Divisão entre inteiros já é inteira.
        _exprs = {
            "mensal": "strftime('%Y-%m', data_faturamento)",
            "trimestral": (
                "strftime('%Y', data_faturamento) || '-T' || "
                "((CAST(strftime('%m', data_faturamento) AS INTEGER) + 2) / 3)"
            ),
            "semestral": (
                "strftime('%Y', data_faturamento) || '-S' || "
                "((CAST(strftime('%m', data_faturamento) AS INTEGER) + 5) / 6)"
            ),
            "anual": "strftime('%Y', data_faturamento)",
        }
    else:  # postgresql (e compatíveis)
        _exprs = {
            "mensal": "TO_CHAR(data_faturamento, 'YYYY-MM')",
            "trimestral": (
                "TO_CHAR(data_faturamento, 'YYYY') || '-T' || "
                "CEIL(EXTRACT(MONTH FROM data_faturamento) / 3.0)::INT"
            ),
            "semestral": (
                "TO_CHAR(data_faturamento, 'YYYY') || '-S' || "
                "CEIL(EXTRACT(MONTH FROM data_faturamento) / 6.0)::INT"
            ),
            "anual": "TO_CHAR(data_faturamento, 'YYYY')",
        }

    periodo_expr = _exprs.get(granularidade)
    if periodo_expr is None:
        raise ValueError(f"granularidade inválida: {granularidade!r}")

    filtros = ["instalacao = :instalacao", "data_faturamento IS NOT NULL"]
    params: dict = {"instalacao": instalacao}
    if inicio:
        filtros.append("data_faturamento >= :inicio")
        params["inicio"] = inicio
    if fim:
        filtros.append("data_faturamento <= :fim")
        params["fim"] = fim

    where = " AND ".join(filtros)
    sql = f"""
        SELECT
            {periodo_expr}                        AS periodo,
            COALESCE(SUM(consumo_kwh), 0)         AS kwh,
            COALESCE(SUM(valor), 0)               AS valor,
            COUNT(*)                              AS n_faturas
        FROM fatura_individual
        WHERE {where}
        GROUP BY {periodo_expr}
        ORDER BY {periodo_expr}
    """
    rows = session.execute(text(sql), params).fetchall()
    return [
        {"periodo": r[0], "kwh": float(r[1]), "valor": float(r[2]), "n_faturas": int(r[3])}
        for r in rows
    ]


def comparativo_anual(
    session: Session,
    complemento_norm: str,
    anos: list[int],
) -> dict[int, list[dict]]:
    """
    Para cada ano em `anos`, retorna a série mensal de valor_total da agrupadora
    identificada por complemento_norm.

    Args:
        complemento_norm: forma canônica ("SEMED-I", etc.).
        anos: lista de anos inteiros a incluir no comparativo.

    Retorna {ano: [{"mes": int, "valor": float}, ...]} — só meses com dados.
    Anos sem dados retornam lista vazia. Ordenado por mês crescente dentro de cada ano.
    """
    if not anos:
        return {}

    # `IN :anos` com bindparam expanding funciona em SQLite e PostgreSQL
    # (o antigo `= ANY(:anos)` era específico de PostgreSQL).
    sql = text("""
        SELECT ano, mes, valor_total
        FROM fatura_agrupadora
        WHERE complemento_norm = :complemento_norm
          AND ano IN :anos
          AND mes IS NOT NULL
          AND valor_total IS NOT NULL
        ORDER BY ano, mes
    """).bindparams(bindparam("anos", expanding=True))
    rows = session.execute(
        sql,
        {"complemento_norm": complemento_norm, "anos": anos},
    ).fetchall()

    resultado: dict[int, list[dict]] = {a: [] for a in anos}
    for ano, mes, valor in rows:
        resultado[ano].append({"mes": mes, "valor": float(valor)})
    return resultado
