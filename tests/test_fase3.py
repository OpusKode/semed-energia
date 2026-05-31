"""
Testes da Fase 3: hierarquia temporal (ano, mes, complemento_norm).

Usa SQLite em memória — sem dependência de PostgreSQL. Após a migração para
SQLite, serie_temporal_unidade e comparativo_anual também rodam em SQLite
(o SQL é montado conforme o dialeto do banco).
"""
import os
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Garante que a raiz do projeto está no sys.path (mesmo que conftest.py já faça)
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.models import Base, FaturaAgrupadora
from db.repository import (
    _derivar_temporal,
    _normalizar_complemento,
    salvar_agrupadora,
    listar_anos,
    listar_meses_do_ano,
    listar_agrupadoras,
    buscar_global,
)


# =============================================================
# Fixture: banco SQLite em memória
# =============================================================

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    # Todas as tabelas são criadas: log_importacao agora usa JSON genérico
    # (mapeado para TEXT no SQLite), não mais JSONB específico de PostgreSQL.
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# =============================================================
# Stub mínimo de DadosCapa para os testes
# =============================================================

@dataclass
class _CapaStub:
    documento: str = "DOC0000001"
    referencia: str | None = "01/2026"
    complemento: str | None = "SEMED I"
    conta_contrato: str | None = None
    cliente_cnpj: str | None = None
    parceiro_negocio: str | None = None
    emissao: object = None
    apresentacao: object = None
    vencimento: object = None
    valor_total: Decimal | None = None
    qtd_faturas_esperada: int | None = None
    consumo_qtd: Decimal | None = None
    consumo_valor: Decimal | None = None
    consumo_ponta_qtd: Decimal | None = None
    consumo_ponta_valor: Decimal | None = None
    consumo_fp_qtd: Decimal | None = None
    consumo_fp_valor: Decimal | None = None
    demanda_ativa_qtd: Decimal | None = None
    demanda_ativa_valor: Decimal | None = None
    demanda_ultra_qtd: Decimal | None = None
    demanda_ultra_valor: Decimal | None = None
    consumo_reat_exc_qtd: Decimal | None = None
    consumo_reat_exc_valor: Decimal | None = None
    consumo_reat_exc_np_qtd: Decimal | None = None
    consumo_reat_exc_np_valor: Decimal | None = None
    consumo_reat_exc_fp_qtd: Decimal | None = None
    consumo_reat_exc_fp_valor: Decimal | None = None
    adicional_bandeira: Decimal | None = None
    icms_total: Decimal | None = None
    cofins_total: Decimal | None = None
    pis_total: Decimal | None = None
    subtotal_1: Decimal | None = None
    trib_reter_irpj: Decimal | None = None
    trib_reter_pis: Decimal | None = None
    trib_reter_cofins: Decimal | None = None
    trib_reter_csll: Decimal | None = None
    credito_dic_fic_dmic: Decimal | None = None
    cip_ilum_pub: Decimal | None = None
    subtotal_2: Decimal | None = None
    demo_energia: Decimal | None = None
    demo_transmissao: Decimal | None = None
    demo_distribuicao: Decimal | None = None
    demo_enc_setoriais: Decimal | None = None
    demo_tributos: Decimal | None = None
    demo_soma: Decimal | None = None
    icms_base_calculo: Decimal | None = None
    icms_aliquota: Decimal | None = None
    icms_valor: Decimal | None = None
    bandeira_amarela: Decimal | None = None
    bandeira_vermelha: Decimal | None = None
    correcao_monetaria: Decimal | None = None
    multa: Decimal | None = None
    juros: Decimal | None = None
    devolucao_icms_lc194: Decimal | None = None
    diferenca_bandeira: Decimal | None = None
    versao_layout: str | None = None


# =============================================================
# Helpers para inserir agrupadoras diretamente (sem salvar_agrupadora)
# =============================================================

def _inserir_ag(session, *, documento, ano, mes, complemento_norm,
                complemento=None, referencia=None, conta_contrato=None):
    ag = FaturaAgrupadora(
        documento=documento,
        referencia=referencia or f"{mes:02d}/{ano}" if (mes and ano) else "01/2000",
        complemento=complemento or complemento_norm,
        conta_contrato=conta_contrato,
        cliente_nome="TESTE",
        status="pendente",
        faturas_importadas=0,
        faturas_com_erro=0,
        ano=ano,
        mes=mes,
        complemento_norm=complemento_norm,
    )
    session.add(ag)
    session.flush()
    return ag


# =============================================================
# Testes de _derivar_temporal / _normalizar_complemento
# =============================================================

def test_derivar_temporal_formatos_variados():
    casos = [
        # (referencia, complemento, esperado_ano, esperado_mes, esperado_norm)
        ("01/2026", "SEMED I",    2026, 1,  "SEMED-I"),
        ("01/2026", "SEMED-I",   2026, 1,  "SEMED-I"),
        ("01/2026", "SEMED  I",  2026, 1,  "SEMED-I"),
        ("01/2026", "SEMED-IV",  2026, 1,  "SEMED-IV"),
        ("01/2026", "SEMED 4",   2026, 1,  "SEMED-IV"),
        ("01/2026", "SEMED4",    2026, 1,  "SEMED-IV"),
        ("01/2026", "SEMED II",  2026, 1,  "SEMED-II"),
        ("01/2026", "SEMED-III", 2026, 1,  "SEMED-III"),
        ("01/2026", None,        2026, 1,  "SEMED-?"),
        (None,      "SEMED I",   None, None, "SEMED-I"),
    ]
    for ref, comp, exp_ano, exp_mes, exp_norm in casos:
        stub = _CapaStub(referencia=ref, complemento=comp)
        ano, mes, norm = _derivar_temporal(stub)
        assert ano == exp_ano,  f"ref={ref!r} comp={comp!r}: ano={ano} != {exp_ano}"
        assert mes == exp_mes,  f"ref={ref!r} comp={comp!r}: mes={mes} != {exp_mes}"
        assert norm == exp_norm, f"ref={ref!r} comp={comp!r}: norm={norm!r} != {exp_norm!r}"


def test_normalizar_complemento_casos_extras():
    assert _normalizar_complemento("semed 1")  == "SEMED-I"
    assert _normalizar_complemento("SEMED-2")  == "SEMED-II"
    assert _normalizar_complemento("SEMED 3")  == "SEMED-III"
    assert _normalizar_complemento("SEMED-4")  == "SEMED-IV"
    assert _normalizar_complemento("SEMED IV") == "SEMED-IV"
    assert _normalizar_complemento("outra")    == "SEMED-?"
    assert _normalizar_complemento("")         == "SEMED-?"
    assert _normalizar_complemento(None)       == "SEMED-?"


# =============================================================
# Testes de salvar_agrupadora
# =============================================================

def test_salvar_agrupadora_popula_temporal(session):
    capa = _CapaStub(referencia="03/2021", complemento="SEMED IV")
    ag = salvar_agrupadora(session, capa)
    assert ag.ano == 2021
    assert ag.mes == 3
    assert ag.complemento_norm == "SEMED-IV"


def test_derivar_temporal_referencia_none():
    """referencia=None → (None, None, ...) — testado em _derivar_temporal diretamente.
    salvar_agrupadora não pode ser chamado com referencia=None (NOT NULL no modelo)."""
    stub = _CapaStub(referencia=None, complemento="SEMED II")
    ano, mes, norm = _derivar_temporal(stub)
    assert ano is None
    assert mes is None
    assert norm == "SEMED-II"


# =============================================================
# Testes de listar_anos
# =============================================================

def test_listar_anos_vazio(session):
    assert listar_anos(session) == []


def test_listar_anos_com_dados(session):
    _inserir_ag(session, documento="A1", ano=2020, mes=1, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="A2", ano=2021, mes=1, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="A3", ano=2021, mes=2, complemento_norm="SEMED-II")
    assert listar_anos(session) == [2021, 2020]


# =============================================================
# Testes de listar_meses_do_ano
# =============================================================

def test_listar_meses_do_ano(session):
    _inserir_ag(session, documento="M1", ano=2024, mes=1, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="M2", ano=2024, mes=3, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="M3", ano=2024, mes=7, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="M4", ano=2023, mes=5, complemento_norm="SEMED-I")
    assert listar_meses_do_ano(session, 2024) == [1, 3, 7]
    assert listar_meses_do_ano(session, 2023) == [5]
    assert listar_meses_do_ano(session, 2099) == []


# =============================================================
# Testes de listar_agrupadoras
# =============================================================

def test_listar_agrupadoras_filtro_hierarquico(session):
    _inserir_ag(session, documento="H1", ano=2024, mes=1, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="H2", ano=2024, mes=1, complemento_norm="SEMED-II")
    _inserir_ag(session, documento="H3", ano=2024, mes=2, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="H4", ano=2025, mes=1, complemento_norm="SEMED-I")

    res = listar_agrupadoras(session, ano=2024, mes=1)
    assert len(res) == 2
    assert {r.documento for r in res} == {"H1", "H2"}

    res = listar_agrupadoras(session, ano=2024)
    assert len(res) == 3

    res = listar_agrupadoras(session)
    assert len(res) == 4


def test_listar_agrupadoras_por_complemento_norm(session):
    _inserir_ag(session, documento="C1", ano=2024, mes=1, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="C2", ano=2024, mes=2, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="C3", ano=2024, mes=1, complemento_norm="SEMED-II")

    res = listar_agrupadoras(session, complemento_norm="SEMED-I")
    assert len(res) == 2
    assert all(r.complemento_norm == "SEMED-I" for r in res)


# =============================================================
# Testes de buscar_global
# =============================================================

def test_buscar_global(session):
    _inserir_ag(
        session,
        documento="610001234567",
        ano=2024, mes=1,
        complemento_norm="SEMED-I",
        complemento="SEMED I",
        conta_contrato="CTRT-001",
    )
    _inserir_ag(
        session,
        documento="610009999999",
        ano=2024, mes=1,
        complemento_norm="SEMED-II",
        complemento="SEMED II",
        conta_contrato="CTRT-002",
    )

    # Busca por fragmento de documento
    res = buscar_global(session, "610001")
    assert len(res) == 1
    assert res[0].documento == "610001234567"

    # Busca por complemento_norm (case-insensitive — SQLite usa LIKE ASCII)
    res = buscar_global(session, "SEMED-I")
    docs = {r.documento for r in res}
    assert "610001234567" in docs

    # Busca por conta_contrato
    res = buscar_global(session, "CTRT-002")
    assert len(res) == 1
    assert res[0].documento == "610009999999"

    # Sem resultados
    res = buscar_global(session, "xxxx")
    assert res == []


def test_buscar_global_case_insensitive(session):
    _inserir_ag(session, documento="DOCX01", ano=2024, mes=1,
                complemento_norm="SEMED-III")
    # SQLite: LIKE é case-insensitive apenas para ASCII (letras A-Z)
    # "semed-iii" vs "SEMED-III" — deve funcionar em SQLite para ASCII
    res = buscar_global(session, "semed-iii")
    assert len(res) == 1


# =============================================================
# Teste de UNIQUE constraint (ano, mes, complemento_norm)
# =============================================================

def test_ux_unique_constraint(session):
    """Segunda inserção com mesmo (ano, mes, complemento_norm) levanta IntegrityError."""
    _inserir_ag(session, documento="UX1", ano=2024, mes=1, complemento_norm="SEMED-I")
    session.commit()

    with pytest.raises(IntegrityError):
        _inserir_ag(session, documento="UX2", ano=2024, mes=1, complemento_norm="SEMED-I")
        session.commit()


def test_unique_permite_multiplos_nulls(session):
    """NULL em qualquer dos 3 campos não viola o UNIQUE (SQL padrão)."""
    ag1 = FaturaAgrupadora(
        documento="NULLDOC1", referencia="01/2020",
        cliente_nome="T", status="pendente", faturas_importadas=0, faturas_com_erro=0,
        ano=None, mes=None, complemento_norm=None,
    )
    ag2 = FaturaAgrupadora(
        documento="NULLDOC2", referencia="02/2020",
        cliente_nome="T", status="pendente", faturas_importadas=0, faturas_com_erro=0,
        ano=None, mes=None, complemento_norm=None,
    )
    session.add(ag1)
    session.add(ag2)
    session.commit()  # não deve levantar IntegrityError


# =============================================================
# Ordenação de listar_agrupadoras
# =============================================================

def test_listar_agrupadoras_ordenacao(session):
    _inserir_ag(session, documento="O1", ano=2023, mes=12, complemento_norm="SEMED-I")
    _inserir_ag(session, documento="O2", ano=2024, mes=1,  complemento_norm="SEMED-II")
    _inserir_ag(session, documento="O3", ano=2024, mes=1,  complemento_norm="SEMED-I")

    res = listar_agrupadoras(session)
    # Mais recente primeiro; mesmo (ano, mes) → complemento_norm asc
    assert res[0].documento == "O3"   # 2024/01 SEMED-I
    assert res[1].documento == "O2"   # 2024/01 SEMED-II
    assert res[2].documento == "O1"   # 2023/12 SEMED-I


# =============================================================
# Meta-teste: smoke ainda passa
# =============================================================

def test_smoke_ainda_passa():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-q", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"test_smoke.py falhou após Fase 3:\n{result.stdout}\n{result.stderr}"
    )
