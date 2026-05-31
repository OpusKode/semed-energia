"""
Parser da página de capa da fatura agrupadora.

Extrai todos os dados consolidados da primeira página do PDF:
- Identificação (documento, referência, CNPJ, SEMED, contrato)
- Energia/Tributos consolidados (consumo, demanda, bandeira, ICMS, etc.)
- Lançamentos e Serviços (retenções, créditos)
- Demonstrativo de Faturamento
- Composição do ICMS

Fase 2 — Suporte multi-versão:
    parsear_texto_capa detecta automaticamente o layout via
    `parser.version_detector.detectar_versao` e usa os patterns e a lógica
    de extração adequados. A assinatura pública NÃO mudou.

    Versões suportadas:
      v2020 — layout 2020/2021: campos antigos (bandeira_amarela/vermelha,
              multa, juros, correção monetária); subtotal_2 positivo.
      v2022 — mesmo core do v2026 + devolucao_icms_lc194 como bonus.
      v2026 — layout moderno (referência original); comportamento idêntico
              ao código pré-Fase 2 (38 campos esperados).
"""
import fitz  # PyMuPDF
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date

from parser import patterns
from parser.version_detector import detectar_versao
from parser.valor_parser import parse_valor_br, parse_quantidade, parse_data_br, parse_int_safe


@dataclass
class DadosCapa:
    documento: str | None = None
    referencia: str | None = None
    complemento: str | None = None
    conta_contrato: str | None = None
    cliente_cnpj: str | None = None
    parceiro_negocio: str | None = None
    emissao: date | None = None
    apresentacao: date | None = None
    vencimento: date | None = None
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

    # ── Campos históricos (Fase 2) ──────────────────────────────────────────
    # Layout 2020/2021: bandeira tarifária separada em amarela e vermelha
    bandeira_amarela: Decimal | None = None
    bandeira_vermelha: Decimal | None = None
    # Layout 2020/2021: encargos por atraso de pagamento
    correcao_monetaria: Decimal | None = None
    multa: Decimal | None = None
    juros: Decimal | None = None
    # Layout 2022+: crédito de devolução ICMS LC 194/2022
    devolucao_icms_lc194: Decimal | None = None
    # Layout 2024+: diferença de bandeira tarifária
    diferenca_bandeira: Decimal | None = None
    # Versão de layout detectada ("v2020" | "v2022" | "v2026")
    versao_layout: str | None = None

    # ── Controle de qualidade ───────────────────────────────────────────────
    campos_extraidos: int = 0
    campos_esperados: int = 0
    avisos: list = field(default_factory=list)

    def to_dict(self) -> dict:
        excluir = {"campos_extraidos", "campos_esperados", "avisos"}
        return {k: v for k, v in self.__dict__.items() if k not in excluir}


# =============================================================
# API pública
# =============================================================

def parsear_capa(
    caminho_pdf: str | Path,
    doc: "fitz.Document | None" = None,
) -> DadosCapa:
    """Parseia os dados da capa (primeira pagina).

    Args:
        caminho_pdf: caminho do PDF (ignorado quando `doc` e fornecido).
        doc: `fitz.Document` ja aberto. Quando passado, NAO e fechado
            aqui — o caller cuida do ciclo de vida. Util para reutilizar
            a mesma abertura entre classifier e capa_parser.
    """
    close_after = False
    pdf = doc
    if pdf is None:
        pdf = fitz.open(str(caminho_pdf))
        close_after = True
    try:
        texto = pdf[0].get_text()
    finally:
        if close_after:
            pdf.close()
    return parsear_texto_capa(texto)


def parsear_texto_capa(texto: str) -> DadosCapa:
    """
    Parseia o texto da capa e retorna DadosCapa com os campos extraídos.

    Detecta automaticamente o layout (v2020/v2022/v2026) e usa a lógica
    de extração correspondente. A assinatura não recebe parâmetro `versao`
    externo — a auto-detecção interna simplifica o caller e elimina risco
    de versão errada por descuido.
    """
    versao = detectar_versao(texto)
    dados = DadosCapa()
    dados.versao_layout = versao

    if versao == "v2020":
        _preencher_v2020(texto, dados)
    else:
        # v2022 e v2026 compartilham o mesmo core (38 campos) — mantém
        # comportamento idêntico ao código pré-Fase 2 para compatibilidade
        # com os goldens existentes.
        _preencher_v2026_core(texto, dados)

        # Campos bonus (extraídos sem contar em campos_esperados)
        if versao == "v2022":
            m = patterns.DEVOLUCAO_ICMS_LC194.search(texto)
            if m:
                dados.devolucao_icms_lc194 = parse_valor_br(m.group(1))
        else:  # v2026
            m = patterns.DIFERENCA_BANDEIRA.search(texto)
            if m:
                dados.diferenca_bandeira = parse_valor_br(m.group(1))

    return dados


# =============================================================
# Extração por versão de layout
# =============================================================

def _preencher_v2026_core(texto: str, dados: DadosCapa) -> None:
    """
    Extrai os 38 campos do layout v2026 (e v2022).

    Lógica idêntica ao código original pré-Fase 2 — garante zero regressão
    nos goldens das fixtures 2022, 2023, 2024, 2025 e 2026.
    """
    campos_total = 0
    campos_ok = 0

    def extrair(pattern, parser=None, campo_nome=""):
        nonlocal campos_total, campos_ok
        campos_total += 1
        m = pattern.search(texto)
        if m:
            campos_ok += 1
            valor = m.group(1)
            return parser(valor) if parser else valor
        if campo_nome:
            dados.avisos.append(f"Campo nao encontrado: {campo_nome}")
        return None

    def extrair_qtd_val(pattern, campo_base):
        nonlocal campos_total, campos_ok
        campos_total += 1
        m = pattern.search(texto)
        if m:
            campos_ok += 1
            return parse_quantidade(m.group(1)), parse_valor_br(m.group(2))
        dados.avisos.append(f"Campo nao encontrado: {campo_base}")
        return None, None

    def extrair_negativo(pattern, campo_nome):
        nonlocal campos_total, campos_ok
        campos_total += 1
        m = pattern.search(texto)
        if m:
            campos_ok += 1
            val = parse_valor_br(m.group(1))
            return -abs(val) if val else None
        dados.avisos.append(f"Campo nao encontrado: {campo_nome}")
        return None

    # Identificacao
    dados.documento = extrair(patterns.DOCUMENTO, campo_nome="documento")
    dados.referencia = extrair(patterns.REFERENCIA, campo_nome="referencia")
    dados.complemento = extrair(patterns.COMPLEMENTO_SEMED, campo_nome="complemento")
    dados.conta_contrato = extrair(patterns.CONTA_CONTRATO, campo_nome="conta_contrato")
    dados.cliente_cnpj = extrair(patterns.CLIENTE_CNPJ, campo_nome="cliente_cnpj")
    dados.parceiro_negocio = extrair(patterns.PARCEIRO_NEGOCIO, campo_nome="parceiro_negocio")
    dados.emissao = extrair(patterns.EMISSAO, parse_data_br, "emissao")
    dados.apresentacao = extrair(patterns.APRESENTACAO, parse_data_br, "apresentacao")
    dados.vencimento = extrair(patterns.VENCIMENTO, parse_data_br, "vencimento")
    dados.qtd_faturas_esperada = extrair(patterns.QTD_FATURAS, parse_int_safe, "qtd_faturas")

    campos_total += 1
    m = patterns.VALOR_TOTAL.search(texto)
    if m:
        dados.valor_total = parse_valor_br(m.group(1))
        campos_ok += 1
    else:
        dados.avisos.append("Campo nao encontrado: valor_total")

    # Energia/Tributos
    dados.consumo_qtd, dados.consumo_valor = extrair_qtd_val(patterns.CONSUMO, "consumo")
    dados.consumo_ponta_qtd, dados.consumo_ponta_valor = extrair_qtd_val(patterns.CONSUMO_PONTA, "consumo_ponta")
    dados.consumo_fp_qtd, dados.consumo_fp_valor = extrair_qtd_val(patterns.CONSUMO_FORA_PONTA, "consumo_fp")
    dados.demanda_ativa_qtd, dados.demanda_ativa_valor = extrair_qtd_val(patterns.DEMANDA_ATIVA, "demanda_ativa")
    dados.demanda_ultra_qtd, dados.demanda_ultra_valor = extrair_qtd_val(patterns.DEMANDA_ULTRA, "demanda_ultra")
    dados.consumo_reat_exc_qtd, dados.consumo_reat_exc_valor = extrair_qtd_val(patterns.CONSUMO_REAT_EXC, "consumo_reat_exc")
    dados.consumo_reat_exc_fp_qtd, dados.consumo_reat_exc_fp_valor = extrair_qtd_val(patterns.CONSUMO_REAT_EXC_FP, "consumo_reat_exc_fp")
    dados.consumo_reat_exc_np_qtd, dados.consumo_reat_exc_np_valor = extrair_qtd_val(patterns.CONSUMO_REAT_EXC_NP, "consumo_reat_exc_np")

    dados.adicional_bandeira = extrair(patterns.ADICIONAL_BANDEIRA, parse_valor_br, "bandeira")
    dados.icms_total = extrair(patterns.ICMS_TOTAL, parse_valor_br, "icms")
    dados.cofins_total = extrair(patterns.COFINS_TOTAL, parse_valor_br, "cofins")
    dados.pis_total = extrair(patterns.PIS_TOTAL, parse_valor_br, "pis")
    dados.subtotal_1 = extrair(patterns.SUBTOTAL_1, parse_valor_br, "subtotal_1")

    # Lancamentos
    dados.trib_reter_irpj = extrair_negativo(patterns.TRIB_RETER_IRPJ, "irpj")
    dados.trib_reter_pis = extrair_negativo(patterns.TRIB_RETER_PIS, "ret_pis")
    dados.trib_reter_cofins = extrair_negativo(patterns.TRIB_RETER_COFINS, "ret_cofins")
    dados.trib_reter_csll = extrair_negativo(patterns.TRIB_RETER_CSLL, "ret_csll")
    dados.credito_dic_fic_dmic = extrair_negativo(patterns.CREDITO_DIC_FIC, "credito_dic")
    dados.cip_ilum_pub = extrair(patterns.CIP_ILUM_PUB, parse_valor_br, "cip_ilum_pub")
    dados.subtotal_2 = extrair_negativo(patterns.SUBTOTAL_2, "subtotal_2")

    # Demonstrativo
    dados.demo_energia = extrair(patterns.DEMO_ENERGIA, parse_valor_br, "demo_energia")
    dados.demo_transmissao = extrair(patterns.DEMO_TRANSMISSAO, parse_valor_br, "demo_transmissao")
    dados.demo_distribuicao = extrair(patterns.DEMO_DISTRIBUICAO, parse_valor_br, "demo_distribuicao")
    dados.demo_enc_setoriais = extrair(patterns.DEMO_ENC_SETORIAIS, parse_valor_br, "demo_enc_setoriais")
    dados.demo_tributos = extrair(patterns.DEMO_TRIBUTOS, parse_valor_br, "demo_tributos")
    dados.demo_soma = extrair(patterns.DEMO_SOMA, parse_valor_br, "demo_soma")

    # ICMS
    campos_total += 1
    m = patterns.ICMS_COMPOSICAO.search(texto)
    if m:
        campos_ok += 1
        dados.icms_base_calculo = parse_valor_br(m.group(1))
        dados.icms_aliquota = parse_valor_br(m.group(2))
        dados.icms_valor = parse_valor_br(m.group(3))
    else:
        dados.avisos.append("Campo nao encontrado: icms_composicao")

    dados.campos_extraidos = campos_ok
    dados.campos_esperados = campos_total  # sempre 38 para v2026/v2022


def _preencher_v2020(texto: str, dados: DadosCapa) -> None:
    """
    Extrai campos do layout 2020/2021 (31 campos esperados).

    Diferenças estruturais em relação ao v2026:
    - Bandeira tarifária: "Adicional Band. Amarela/Vermelha" (separada por cor)
      em vez de "Adicional Bandeira" (valor único). Ambas são positivas.
    - Subtotal 2: POSITIVO em v2020 (representa encargos: multa+juros+correção)
      ao contrário do v2026 onde é negativo (créditos). Armazenado sem inversão.
    - Campos ausentes no layout antigo (omitidos do dict para não inflar
      campos_esperados com falsos "não encontrados"):
        consumo_ponta, consumo_fp (não discriminados separadamente),
        demanda_ativa, demanda_ultra, consumo_reat_exc_*,
        trib_reter_irpj/pis/cofins/csll, credito_dic_fic_dmic, cip_ilum_pub.
    - Campos exclusivos v2020: bandeira_amarela, bandeira_vermelha,
      correcao_monetaria, multa, juros.

    Total: 10 identificação + 1 valor_total + 5 energia + 1 subtotal2
           + 5 v2020-específicos + 6 demonstrativo + 1 icms_composicao
           = 29 campos_esperados.
    """
    campos_total = 0
    campos_ok = 0

    def extrair(pattern, parser=None, campo_nome=""):
        nonlocal campos_total, campos_ok
        campos_total += 1
        m = pattern.search(texto)
        if m:
            campos_ok += 1
            valor = m.group(1)
            return parser(valor) if parser else valor
        if campo_nome:
            dados.avisos.append(f"Campo nao encontrado: {campo_nome}")
        return None

    def extrair_qtd_val(pattern, campo_base):
        nonlocal campos_total, campos_ok
        campos_total += 1
        m = pattern.search(texto)
        if m:
            campos_ok += 1
            return parse_quantidade(m.group(1)), parse_valor_br(m.group(2))
        dados.avisos.append(f"Campo nao encontrado: {campo_base}")
        return None, None

    # ── Identificação (10 campos — mesmos patterns do v2026) ──
    dados.documento = extrair(patterns.DOCUMENTO, campo_nome="documento")
    dados.referencia = extrair(patterns.REFERENCIA, campo_nome="referencia")
    dados.complemento = extrair(patterns.COMPLEMENTO_SEMED, campo_nome="complemento")
    dados.conta_contrato = extrair(patterns.CONTA_CONTRATO, campo_nome="conta_contrato")
    dados.cliente_cnpj = extrair(patterns.CLIENTE_CNPJ, campo_nome="cliente_cnpj")
    dados.parceiro_negocio = extrair(patterns.PARCEIRO_NEGOCIO, campo_nome="parceiro_negocio")
    dados.emissao = extrair(patterns.EMISSAO, parse_data_br, "emissao")
    dados.apresentacao = extrair(patterns.APRESENTACAO, parse_data_br, "apresentacao")
    dados.vencimento = extrair(patterns.VENCIMENTO, parse_data_br, "vencimento")
    dados.qtd_faturas_esperada = extrair(patterns.QTD_FATURAS, parse_int_safe, "qtd_faturas")

    # ── Valor total (tratamento especial — 2 alternativas de pattern) ──
    campos_total += 1
    m = patterns.VALOR_TOTAL.search(texto)
    if m:
        dados.valor_total = parse_valor_br(m.group(1))
        campos_ok += 1
    else:
        dados.avisos.append("Campo nao encontrado: valor_total")

    # ── Energia/Tributos presentes em 2020/2021 ──
    # Apenas "Consumo" genérico — sem discriminação ponta/fora ponta/demanda.
    dados.consumo_qtd, dados.consumo_valor = extrair_qtd_val(patterns.CONSUMO, "consumo")
    dados.icms_total = extrair(patterns.ICMS_TOTAL, parse_valor_br, "icms")
    dados.cofins_total = extrair(patterns.COFINS_TOTAL, parse_valor_br, "cofins")
    dados.pis_total = extrair(patterns.PIS_TOTAL, parse_valor_br, "pis")
    dados.subtotal_1 = extrair(patterns.SUBTOTAL_1, parse_valor_br, "subtotal_1")

    # ── Lançamentos: Subtotal 2 POSITIVO em v2020 (encargos, não créditos) ──
    dados.subtotal_2 = extrair(patterns.SUBTOTAL_2, parse_valor_br, "subtotal_2")

    # ── Campos exclusivos v2020/2021 ──
    dados.bandeira_amarela = extrair(
        patterns.ADICIONAL_BANDEIRA_AMARELA, parse_valor_br, "bandeira_amarela"
    )
    dados.bandeira_vermelha = extrair(
        patterns.ADICIONAL_BANDEIRA_VERMELHA, parse_valor_br, "bandeira_vermelha"
    )
    dados.correcao_monetaria = extrair(
        patterns.CORRECAO_MONETARIA, parse_valor_br, "correcao_monetaria"
    )
    dados.multa = extrair(patterns.MULTA, parse_valor_br, "multa")
    dados.juros = extrair(patterns.JUROS, parse_valor_br, "juros")

    # ── Demonstrativo (presente em todos os layouts) ──
    dados.demo_energia = extrair(patterns.DEMO_ENERGIA, parse_valor_br, "demo_energia")
    dados.demo_transmissao = extrair(patterns.DEMO_TRANSMISSAO, parse_valor_br, "demo_transmissao")
    dados.demo_distribuicao = extrair(patterns.DEMO_DISTRIBUICAO, parse_valor_br, "demo_distribuicao")
    dados.demo_enc_setoriais = extrair(patterns.DEMO_ENC_SETORIAIS, parse_valor_br, "demo_enc_setoriais")
    dados.demo_tributos = extrair(patterns.DEMO_TRIBUTOS, parse_valor_br, "demo_tributos")
    dados.demo_soma = extrair(patterns.DEMO_SOMA, parse_valor_br, "demo_soma")

    # ── ICMS Composição (tratamento especial — 3 grupos) ──
    campos_total += 1
    m = patterns.ICMS_COMPOSICAO.search(texto)
    if m:
        campos_ok += 1
        dados.icms_base_calculo = parse_valor_br(m.group(1))
        dados.icms_aliquota = parse_valor_br(m.group(2))
        dados.icms_valor = parse_valor_br(m.group(3))
    else:
        dados.avisos.append("Campo nao encontrado: icms_composicao")

    dados.campos_extraidos = campos_ok
    dados.campos_esperados = campos_total  # 31 para v2020
