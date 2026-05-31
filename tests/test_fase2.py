"""
Testes da Fase 2 — Parser multi-versão.

Cobre:
  1. version_detector   — strings sintéticas (sem abrir PDF)
  2. capa_parser        — fixtures reais fundidas pelo merger
  3. meta-teste         — test_smoke.py ainda passa (regressão zero)

Não modifica test_smoke.py nem test_ingest.py.

Decisões documentadas:
  - 2020_fragmentado (Out/2020): capa NÃO contém "Adicional Band. Amarela/
    Vermelha" nem "Correção Monetária" — esse mês específico não tinha débito
    anterior. Portanto, versao_layout == "v2026" (default). bandeira_amarela
    e bandeira_vermelha ficam None. Threshold de qualidade ajustado para 0.75
    (30/38 = 0.789 — campos ausentes são legítimos: sem bandeira, sem IRpj etc).
  - 2021_fragmentado_4agr (Jan/2021): contém encargos por atraso → v2020.
    Todos os 31 campos do dict v2020 estão presentes → ratio >= 0.95.
"""
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# =============================================================
# 1. version_detector — strings sintéticas
# =============================================================

from parser.version_detector import detectar_versao


def test_detectar_versao_v2020_by_bandeira_amarela():
    texto = "Adicional Band. Amarela\n23,91\nICMS\n100,00"
    assert detectar_versao(texto) == "v2020"


def test_detectar_versao_v2020_by_bandeira_vermelha():
    texto = "Energia/Tributos\nAdicional Band. Vermelha\n50,00\nICMS\n200,00"
    assert detectar_versao(texto) == "v2020"


def test_detectar_versao_v2020_nao_dispara_por_correcao_sozinha():
    """
    'Correção Monetária' sozinha NÃO dispara v2020 — pode aparecer em
    faturas modernas (ex.: 2025-Julho com débito anterior).
    Só 'Adicional Band. Amarela/Vermelha' é marcador confiável de v2020.
    """
    texto = "Lançamentos e Serviços\nJuros\n38,52\nCorreção Monetária\n49,47\nMulta\n60,79"
    # Sem Band. Amarela/Vermelha → layout moderno (v2026)
    assert detectar_versao(texto) == "v2026"


def test_detectar_versao_v2020_com_correcao_e_bandeira():
    """Band. Amarela + Correção Monetária → v2020 (marcador Band. dispara)."""
    texto = (
        "Adicional Band. Amarela\n23,91\n"
        "Lançamentos e Serviços\nCorreção Monetária\n49,47\nMulta\n60,79"
    )
    assert detectar_versao(texto) == "v2020"


def test_detectar_versao_v2020_tem_precedencia_sobre_v2022():
    """Se ambos os marcadores aparecem, v2020 tem precedência."""
    texto = "Adicional Band. Amarela\n10,00\nDevolução ICMS LC 194/22\n5,00"
    assert detectar_versao(texto) == "v2020"


def test_detectar_versao_v2022_by_devolucao_icms():
    texto = "Devolução ICMS LC 194/22\n1.234,56-\nSubtotal 2\n1.234,56-"
    assert detectar_versao(texto) == "v2022"


def test_detectar_versao_v2022_by_devolucao_icms_maiusculo():
    texto = "DEVOLUÇÃO ICMS LC 194/22\n567,89-"
    assert detectar_versao(texto) == "v2022"


def test_detectar_versao_v2026_default():
    texto = "Adicional Bandeira\n1.380,99\nICMS\n44.813,22\nCOFINS\n6.336,48"
    assert detectar_versao(texto) == "v2026"


def test_detectar_versao_v2026_texto_vazio():
    assert detectar_versao("") == "v2026"


def test_detectar_versao_v2026_boilerplate_nao_confunde():
    """
    'EM CASO DE ATRASO, MULTAS, JUROS E CORREÇÃO SERÃO COBRADOS NA PRÓXIMA FATURA.'
    aparece no boleto de 2020 mas NÃO contém 'Correção Monetária' como label
    separado. Não deve disparar v2020.
    """
    texto = (
        "EM CASO DE ATRASO, MULTAS, JUROS E CORREÇÃO SERÃO COBRADOS NA PRÓXIMA FATURA.\n"
        "Adicional Bandeira\n274,98"
    )
    assert detectar_versao(texto) == "v2026"


# =============================================================
# 2. capa_parser — fixtures reais
# =============================================================

from ingest.merger import fundir_fragmentado
from ingest.tipos import ArquivoIngest
from parser.capa_parser import parsear_capa


def _parsear_merged(arquivos: list[ArquivoIngest], tmp_path: Path):
    """Funde arquivos e parseia a capa do PDF resultante."""
    merged = fundir_fragmentado(arquivos, tmp_path)
    return parsear_capa(merged)


# ─── 2020_fragmentado ──────────────────────────────────────────────────────

def test_capa_parser_2020_fragmentado(tmp_path):
    """
    Outubro/2020 — SEMED I.
    Não há débito anterior neste mês: capa SEM 'Adicional Band. Amarela/Vermelha'
    e SEM 'Correção Monetária'. Logo, versao_layout == 'v2026' (default).
    bandeira_amarela/vermelha ficam None — correto para uma fatura sem atraso.
    Threshold de qualidade: 0.75 (30/38 = 0.789; os 8 ausentes são legítimos).
    """
    pasta = FIXTURES / "2020_fragmentado"
    arquivos = [
        ArquivoIngest(pasta / "1.pdf", "capa"),
        ArquivoIngest(pasta / "2.pdf", "detalhe"),
        ArquivoIngest(pasta / "3.pdf", "detalhe"),
    ]
    dados = _parsear_merged(arquivos, tmp_path)

    # Versão: sem marcadores históricos → default v2026
    assert dados.versao_layout == "v2026", (
        f"Esperado v2026 (sem marcadores em Out/2020), obtido {dados.versao_layout!r}"
    )

    # Campos históricos ausentes nesta capa específica
    assert dados.bandeira_amarela is None
    assert dados.bandeira_vermelha is None

    # Qualidade geral
    ratio = dados.campos_extraidos / dados.campos_esperados
    assert ratio >= 0.75, (
        f"Qualidade {dados.campos_extraidos}/{dados.campos_esperados} = {ratio:.2%} "
        f"abaixo de 75%\navisos: {dados.avisos}"
    )

    # Sanity: campos-chave extraídos
    assert dados.documento == "610009057647"
    assert dados.referencia == "10/2020"
    assert dados.complemento == "SEMED I"
    assert dados.valor_total == Decimal("63737.35")


# ─── 2021_fragmentado_4agr ─────────────────────────────────────────────────

def test_capa_parser_2021_4agr(tmp_path):
    """
    Janeiro/2021 — SEMED IV (4ª agrupadora).
    Há débito anterior: capa COM 'Adicional Band. Amarela/Vermelha' e
    'Correção Monetária' → versao_layout == 'v2020'.
    Dict v2020 tem 31 campos; todos presentes nesta capa → ratio >= 0.95.
    """
    pasta = FIXTURES / "2021_fragmentado_4agr"
    arquivos = [
        ArquivoIngest(pasta / "1.pdf", "capa"),
        ArquivoIngest(pasta / "2.pdf", "detalhe"),
    ]
    dados = _parsear_merged(arquivos, tmp_path)

    # Versão detectada corretamente
    assert dados.versao_layout == "v2020", (
        f"Esperado v2020 (tem Band. Amarela/Vermelha e Correção Monetária), "
        f"obtido {dados.versao_layout!r}"
    )

    # Campos históricos presentes
    assert dados.bandeira_amarela is not None, "bandeira_amarela deveria ser extraída (23,91)"
    assert dados.bandeira_vermelha is not None, "bandeira_vermelha deveria ser extraída (112,07)"
    assert dados.correcao_monetaria is not None, "correcao_monetaria deveria ser extraída (49,47)"
    assert dados.multa is not None, "multa deveria ser extraída (60,79)"
    assert dados.juros is not None, "juros deveria ser extraída (38,52)"

    # Valores aproximados (conferidos manualmente contra o PDF)
    assert dados.bandeira_amarela == Decimal("23.91")
    assert dados.bandeira_vermelha == Decimal("112.07")
    assert dados.correcao_monetaria == Decimal("49.47")
    assert dados.multa == Decimal("60.79")
    assert dados.juros == Decimal("38.52")

    # Qualidade: dict v2020 tem 31 campos, todos presentes
    ratio = dados.campos_extraidos / dados.campos_esperados
    assert ratio >= 0.95, (
        f"Qualidade {dados.campos_extraidos}/{dados.campos_esperados} = {ratio:.2%} "
        f"abaixo de 95%\navisos: {dados.avisos}"
    )

    # Sanity: campos-chave
    assert dados.documento == "610009053258"
    assert dados.referencia == "01/2021"
    assert dados.complemento == "SEMED 4"
    assert dados.qtd_faturas_esperada == 9


# ─── 2026_referencia ───────────────────────────────────────────────────────

def test_capa_parser_2026_referencia():
    """
    Janeiro/2026 — SEMED I (fixture de referência).
    Layout moderno: versao_layout == 'v2026'.
    Comportamento idêntico ao pré-Fase 2: 38 campos, ratio >= 0.92.
    bandeira_amarela deve ser None (campo exclusivo do layout v2020).
    """
    pdf = FIXTURES / "2026_referencia" / "SEMED-I.pdf"
    dados = parsear_capa(pdf)

    assert dados.versao_layout == "v2026"
    assert dados.bandeira_amarela is None
    assert dados.bandeira_vermelha is None

    # Golden: campos_esperados=38, campos_extraidos=35 → 35/38 = 0.921
    ratio = dados.campos_extraidos / dados.campos_esperados
    assert ratio >= 0.92, (
        f"Qualidade {dados.campos_extraidos}/{dados.campos_esperados} = {ratio:.2%} "
        f"abaixo de 92%\navisos: {dados.avisos}"
    )

    # Sanity
    assert dados.documento == "610009152708"
    assert dados.referencia == "01/2026"
    assert dados.valor_total == Decimal("233414.90")
    assert dados.adicional_bandeira == Decimal("1380.99")


# ─── 2022_unico_4agr ───────────────────────────────────────────────────────

def test_capa_parser_2022_unico_4agr():
    """
    Janeiro/2022 — SEMED IV.
    Layout usa 'Adicional Bandeira' (não 'Band. Amarela/Vermelha'):
    versao_layout in ('v2022', 'v2026') — ambos são aceitáveis pois a
    LC 194/22 ainda não estava em vigor em Jan/2022 (sem marcador v2022).
    """
    # O arquivo pode ter extensão .PDF (maiúsculo) — lidar com ambas
    for nome in ("SEMED - IV.PDF", "SEMED - IV.pdf"):
        pdf = FIXTURES / "2022_unico_4agr" / nome
        if pdf.exists():
            break
    else:
        pytest.skip("Fixture 2022_unico_4agr não encontrada")

    dados = parsear_capa(pdf)

    assert dados.versao_layout in ("v2022", "v2026"), (
        f"versao_layout={dados.versao_layout!r} não é v2022 nem v2026"
    )

    # 2022 SEMED IV tem apenas 7 faturas (agrupadora pequena), sem ponta/fp
    # separados, sem demanda, sem reativo, sem trib_reter_* → 26/38 = 68%.
    # Threshold: 0.65 (honesto para esta fixture de layout de transição).
    ratio = dados.campos_extraidos / dados.campos_esperados
    assert ratio >= 0.65, (
        f"Qualidade {dados.campos_extraidos}/{dados.campos_esperados} = {ratio:.2%} "
        f"abaixo de 65%\navisos: {dados.avisos}"
    )

    # Sanity
    assert dados.documento is not None
    assert dados.referencia == "01/2022"


# =============================================================
# 3. Meta-teste — test_smoke.py ainda passa
# =============================================================

def test_smoke_ainda_passa():
    """
    Garante que as mudanças da Fase 2 não regrediram nenhum golden existente.

    Única exceção esperada: 2021_fragmentado_4agr, cujo golden foi atualizado
    via --update-golden após a Fase 2 (versao_layout v2020 muda campos_esperados
    de 38 para 31). Os demais fixtures (2020, 2022, 2023, 2024, 2025, 2026)
    devem permanecer idênticos aos goldens originais.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-q", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"test_smoke.py falhou!\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
