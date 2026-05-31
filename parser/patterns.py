"""
Regex patterns centralizados para extração de dados das faturas.
Todos os patterns são testados contra os 3 PDFs de referência:
SEMED-I (88 faturas), SEMED-II (33 faturas), SEMED-III (7 faturas).
"""
import re

# ─── Padrões da Capa (Página 1) ─────────────────────────────

# Identificação do documento
DOCUMENTO = re.compile(r"EMISSÃO:.*?(\d{12})", re.DOTALL)
REFERENCIA = re.compile(r"REFERÊNCIA:\s*([\d/]+)")
EMISSAO = re.compile(r"EMISSÃO:\s*([\d.]+)")
APRESENTACAO = re.compile(r"APRESENTAÇÃO:\s*([\d.]+)")

# Identificação do cliente
CLIENTE_CNPJ = re.compile(r"CNPJ:([\d./-]+)")
PARCEIRO_NEGOCIO = re.compile(r"PARCEIRO DE NEGÓCIO:\s*(\d+)")
COMPLEMENTO_SEMED = re.compile(r"(SEMED\s+\w+)")
CONTA_CONTRATO = re.compile(r"(400001\d{4})")
VENCIMENTO = re.compile(r"VENCIMENTO\n([\d.]+)")

# Valor total
VALOR_TOTAL = re.compile(r"(?:VALOR.*?VENCIMENTO|VALOR DOCUMENTO)\s*\n\s*R\$\s*([\d.,]+)", re.DOTALL)

# Quantidade de faturas agrupadas
QTD_FATURAS = re.compile(r"débito de (\d+) fatura")

# Concessionária
CONCESSIONARIA = re.compile(r"EQUATORIAL PARÁ", re.IGNORECASE)


# ─── Energia/Tributos (Capa) ────────────────────────────────

# Campos com quantidade + valor (2 números após o label)
CONSUMO = re.compile(r"(?<!Reativo )(?<!Fora )(?<!a )Consumo\n([\d.]+)\n([\d.,]+)")
CONSUMO_PONTA = re.compile(r"Consumo Ponta\n([\d.]+)\n([\d.,]+)")
CONSUMO_FORA_PONTA = re.compile(r"Consumo Fora Ponta\n([\d.]+)\n([\d.,]+)")
DEMANDA_ATIVA = re.compile(r"Demanda Ativa\n([\d.]+)\n([\d.,]+)")
DEMANDA_ULTRA = re.compile(r"Demanda Ultrapassagem\n([\d.]+)\n([\d.,]+)")
CONSUMO_REAT_EXC = re.compile(r"Consumo Reativo Excedente\n([\d.]+)\n([\d.,]+)")
CONSUMO_REAT_EXC_FP = re.compile(r"Consumo Reativo Excedente FP\n([\d.]+)\n([\d.,]+)")
CONSUMO_REAT_EXC_NP = re.compile(r"Consumo Reativo Excedente NP\n([\d.]+)\n([\d.,]+)")

# Campos só com valor
ADICIONAL_BANDEIRA = re.compile(r"Adicional Bandeira\n([\d.,]+)")
ICMS_TOTAL = re.compile(r"^ICMS\n([\d.,]+)", re.MULTILINE)
COFINS_TOTAL = re.compile(r"^COFINS\n([\d.,]+)", re.MULTILINE)
PIS_TOTAL = re.compile(r"^PIS\n([\d.,]+)", re.MULTILINE)
SUBTOTAL_1 = re.compile(r"Subtotal 1\n\s*([\d.,]+)")


# ─── Lançamentos e Serviços (Capa) ──────────────────────────

TRIB_RETER_IRPJ = re.compile(r"Tributo a Reter IRPJ\n\s*([\d.,]+)-?")
TRIB_RETER_PIS = re.compile(r"Tributo a Reter PIS\n\s*([\d.,]+)-?")
TRIB_RETER_COFINS = re.compile(r"Tributo a Reter COFINS\n\s*([\d.,]+)-?")
TRIB_RETER_CSLL = re.compile(r"Tributo a Reter CSLL\n\s*([\d.,]+)-?")
CREDITO_DIC_FIC = re.compile(r"Crédito DIC/FIC/DMIC\n\s*([\d.,]+)-?")
CIP_ILUM_PUB = re.compile(r"Cip-Ilum Pub Pref Munic\n\s*([\d.,]+)")
SUBTOTAL_2 = re.compile(r"Subtotal 2\n\s*([\d.,]+)-?")


# ─── Demonstrativo (Capa) ───────────────────────────────────

DEMO_ENERGIA = re.compile(r"ENERGIA\n\s*([\d.,]+)")
DEMO_TRANSMISSAO = re.compile(r"TRANSMISSÃO\n\s*([\d.,]+)")
DEMO_DISTRIBUICAO = re.compile(r"DISTRIBUIÇÃO\n\s*([\d.,]+)")
DEMO_ENC_SETORIAIS = re.compile(r"ENC\. SETORIAIS\n\s*([\d.,]+)")
DEMO_TRIBUTOS = re.compile(r"TRIBUTOS\n\s*([\d.,]+)")
DEMO_SOMA = re.compile(r"Soma Demonstrativa\s*([\d.,]+)")

# ICMS Composição (3 valores antes de "AGÊNCIA")
ICMS_COMPOSICAO = re.compile(
    r"([\d.,]+)\s*\n\s*(\d+,\d+)\n\s*([\d.,]+)\s*\nAGÊNCIA"
)


# ─── Classificação de Páginas ────────────────────────────────

PAGINA_CAPA = re.compile(r"FATURA AGRUPADORA")
PAGINA_DETALHE = re.compile(r"RELAÇÃO DE FATURAS AGRUPADORAS")
# No PyMuPDF, "Tensão" e "A4"/"B3" ficam em linhas separadas (extração por coluna).
# Buscar o valor de tensão como token isolado em linha própria.
TENSAO_B3 = re.compile(r"\nB3\n")
TENSAO_A4 = re.compile(r"\nA4\n")
PAGINA_RODAPE = re.compile(r"Pág:\s*(\d+)\s*de\s*(\d+)")


# ─── Patterns históricos (exclusivos de layouts antigos) ────────────────────
#
# Todos os patterns abaixo são novos (Fase 2). Os nomes seguem a convenção
# do restante do módulo e são exportados individualmente para uso direto
# em capa_parser.py, bem como agrupados nos dicionários versionados abaixo.

# Layout 2020/2021: bandeira tarifária aparece separada em amarela e vermelha
ADICIONAL_BANDEIRA_AMARELA = re.compile(r"Adicional Band\. Amarela\n([\d.,]+)")
ADICIONAL_BANDEIRA_VERMELHA = re.compile(r"Adicional Band\. Vermelha\n([\d.,]+)")

# Layout 2020/2021: encargos por atraso listados como itens em Lançamentos e Serviços
# Lookbehind (?<!\w) evita o boilerplate "MULTAS, JUROS E CORREÇÃO" da linha de aviso
# do boleto (toda maiúscula e sem newline+número logo após).
CORRECAO_MONETARIA = re.compile(r"Correção Monetária\n([\d.,]+)", re.IGNORECASE)
MULTA = re.compile(r"(?<!\w)Multa\n([\d.,]+)")
JUROS = re.compile(r"(?<!\w)Juros\n([\d.,]+)")

# Layout 2022+: crédito de devolução ICMS LC 194/2022
DEVOLUCAO_ICMS_LC194 = re.compile(r"Devolução ICMS LC 194/22\n([\d.,]+)-?", re.IGNORECASE)

# Layout 2024+: diferença de bandeira (vista em 2024-OUT consolidado)
DIFERENCA_BANDEIRA = re.compile(r"Diferença Bandeira\n([\d.,]+)")


# ─── Dicionários versionados de patterns da capa ───────────────────────────
#
# Cada dicionário contém os patterns relevantes para aquela versão de layout.
# Os campos de quantidade+valor (consumo, demanda, etc.) mapeiam para o mesmo
# pattern de 2 grupos — o capa_parser distingue pelo nome do campo.
#
# Regra: manter os mesmos nomes de chave em todos os dicionários para campos
# comuns; campos exclusivos de uma versão aparecem apenas naquele dicionário.
# Os imports em capa_parser.py, classifier.py e detalhe_parser.py NÃO
# precisam mudar — as variáveis originais (DOCUMENTO, REFERENCIA, ...) estão
# preservadas acima.

PATTERNS_V_2020: dict[str, re.Pattern] = {
    # ── Identificação ──
    "documento":         DOCUMENTO,
    "referencia":        REFERENCIA,
    "complemento":       COMPLEMENTO_SEMED,
    "conta_contrato":    CONTA_CONTRATO,
    "cliente_cnpj":      CLIENTE_CNPJ,
    "parceiro_negocio":  PARCEIRO_NEGOCIO,
    "emissao":           EMISSAO,
    "apresentacao":      APRESENTACAO,
    "vencimento":        VENCIMENTO,
    "qtd_faturas":       QTD_FATURAS,
    # valor_total tratado separadamente no capa_parser (2 grupos alternativos)
    # ── Energia/Tributos presentes em 2020/2021 ──
    # (sem consumo_ponta/fp separados, sem demanda_ativa/ultra, sem reat_exc,
    #  sem adicional_bandeira — layout antigo usa "Adicional Band. Amarela/Vermelha")
    "consumo":           CONSUMO,        # 2 grupos: qty + val
    "icms_total":        ICMS_TOTAL,
    "cofins_total":      COFINS_TOTAL,
    "pis_total":         PIS_TOTAL,
    "subtotal_1":        SUBTOTAL_1,
    # ── Lançamentos: em 2020/2021 subtotal_2 é POSITIVO (encargos) ──
    # (sem trib_reter_*, sem credito_dic_fic, sem cip_ilum_pub)
    "subtotal_2":        SUBTOTAL_2,
    # ── Campos exclusivos v2020/2021 ──
    "bandeira_amarela":  ADICIONAL_BANDEIRA_AMARELA,
    "bandeira_vermelha": ADICIONAL_BANDEIRA_VERMELHA,
    "correcao_monetaria": CORRECAO_MONETARIA,
    "multa":             MULTA,
    "juros":             JUROS,
    # ── Demonstrativo (presente em todos os layouts) ──
    "demo_energia":         DEMO_ENERGIA,
    "demo_transmissao":     DEMO_TRANSMISSAO,
    "demo_distribuicao":    DEMO_DISTRIBUICAO,
    "demo_enc_setoriais":   DEMO_ENC_SETORIAIS,
    "demo_tributos":        DEMO_TRIBUTOS,
    "demo_soma":            DEMO_SOMA,
    # icms_composicao tratado separadamente no capa_parser (3 grupos)
}
# Total de campos tentados via PATTERNS_V_2020: 24 core + 5 v2020-específicos = 29
# (valor_total e icms_composicao são tratados fora do loop principal: +2 = 31 total)

PATTERNS_V_2022: dict[str, re.Pattern] = {
    # ── Identificação ──
    "documento":         DOCUMENTO,
    "referencia":        REFERENCIA,
    "complemento":       COMPLEMENTO_SEMED,
    "conta_contrato":    CONTA_CONTRATO,
    "cliente_cnpj":      CLIENTE_CNPJ,
    "parceiro_negocio":  PARCEIRO_NEGOCIO,
    "emissao":           EMISSAO,
    "apresentacao":      APRESENTACAO,
    "vencimento":        VENCIMENTO,
    "qtd_faturas":       QTD_FATURAS,
    # ── Energia/Tributos (mesmo conjunto do v2026) ──
    "consumo":           CONSUMO,
    "consumo_ponta":     CONSUMO_PONTA,
    "consumo_fp":        CONSUMO_FORA_PONTA,
    "demanda_ativa":     DEMANDA_ATIVA,
    "demanda_ultra":     DEMANDA_ULTRA,
    "consumo_reat_exc":  CONSUMO_REAT_EXC,
    "consumo_reat_exc_fp": CONSUMO_REAT_EXC_FP,
    "consumo_reat_exc_np": CONSUMO_REAT_EXC_NP,
    "adicional_bandeira": ADICIONAL_BANDEIRA,
    "icms_total":        ICMS_TOTAL,
    "cofins_total":      COFINS_TOTAL,
    "pis_total":         PIS_TOTAL,
    "subtotal_1":        SUBTOTAL_1,
    # ── Lançamentos (mesmo conjunto do v2026) ──
    "trib_reter_irpj":   TRIB_RETER_IRPJ,
    "trib_reter_pis":    TRIB_RETER_PIS,
    "trib_reter_cofins": TRIB_RETER_COFINS,
    "trib_reter_csll":   TRIB_RETER_CSLL,
    "credito_dic_fic":   CREDITO_DIC_FIC,
    "cip_ilum_pub":      CIP_ILUM_PUB,
    "subtotal_2":        SUBTOTAL_2,
    # ── Demonstrativo ──
    "demo_energia":      DEMO_ENERGIA,
    "demo_transmissao":  DEMO_TRANSMISSAO,
    "demo_distribuicao": DEMO_DISTRIBUICAO,
    "demo_enc_setoriais": DEMO_ENC_SETORIAIS,
    "demo_tributos":     DEMO_TRIBUTOS,
    "demo_soma":         DEMO_SOMA,
    # ── Exclusivo v2022 ──
    # devolucao_icms_lc194 é extraído como bonus (não conta em campos_esperados)
    "devolucao_icms_lc194": DEVOLUCAO_ICMS_LC194,
}
# Mesmos 38 campos core do v2026 — comportamento idêntico para
# compatibilidade com goldens.

PATTERNS_V_2026: dict[str, re.Pattern] = {
    # ── Identificação ──
    "documento":         DOCUMENTO,
    "referencia":        REFERENCIA,
    "complemento":       COMPLEMENTO_SEMED,
    "conta_contrato":    CONTA_CONTRATO,
    "cliente_cnpj":      CLIENTE_CNPJ,
    "parceiro_negocio":  PARCEIRO_NEGOCIO,
    "emissao":           EMISSAO,
    "apresentacao":      APRESENTACAO,
    "vencimento":        VENCIMENTO,
    "qtd_faturas":       QTD_FATURAS,
    # ── Energia/Tributos ──
    "consumo":           CONSUMO,
    "consumo_ponta":     CONSUMO_PONTA,
    "consumo_fp":        CONSUMO_FORA_PONTA,
    "demanda_ativa":     DEMANDA_ATIVA,
    "demanda_ultra":     DEMANDA_ULTRA,
    "consumo_reat_exc":  CONSUMO_REAT_EXC,
    "consumo_reat_exc_fp": CONSUMO_REAT_EXC_FP,
    "consumo_reat_exc_np": CONSUMO_REAT_EXC_NP,
    "adicional_bandeira": ADICIONAL_BANDEIRA,
    "icms_total":        ICMS_TOTAL,
    "cofins_total":      COFINS_TOTAL,
    "pis_total":         PIS_TOTAL,
    "subtotal_1":        SUBTOTAL_1,
    # ── Lançamentos ──
    "trib_reter_irpj":   TRIB_RETER_IRPJ,
    "trib_reter_pis":    TRIB_RETER_PIS,
    "trib_reter_cofins": TRIB_RETER_COFINS,
    "trib_reter_csll":   TRIB_RETER_CSLL,
    "credito_dic_fic":   CREDITO_DIC_FIC,
    "cip_ilum_pub":      CIP_ILUM_PUB,
    "subtotal_2":        SUBTOTAL_2,
    # ── Demonstrativo ──
    "demo_energia":      DEMO_ENERGIA,
    "demo_transmissao":  DEMO_TRANSMISSAO,
    "demo_distribuicao": DEMO_DISTRIBUICAO,
    "demo_enc_setoriais": DEMO_ENC_SETORIAIS,
    "demo_tributos":     DEMO_TRIBUTOS,
    "demo_soma":         DEMO_SOMA,
    # ── Exclusivo v2026 ──
    # diferenca_bandeira é extraído como bonus (não conta em campos_esperados)
    "diferenca_bandeira": DIFERENCA_BANDEIRA,
}
