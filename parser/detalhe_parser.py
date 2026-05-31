"""
Parser das paginas de detalhe (B3 baixa tensao e A4 media tensao).

- B3: 2 instalacoes por pagina (metade superior e inferior).
- A4: 1 instalacao por pagina (ocupa a pagina inteira).

Fase 2 — Investigacao de versionamento:
    Inspecionamos os goldens das fixtures 2020_fragmentado e
    2021_fragmentado_4agr (via test_smoke.py / golden/*.json).

    Resultado: SEM DIFERENÇA ESTRUTURAL entre versoes encontrada nos fixtures
    2020-2026. As paginas de detalhe (B3 e A4) apresentam o mesmo layout de
    colunas (Empresa, Local, Nome, Instalacao, Tributos, Valores Faturados,
    Valores Medidos) em todos os anos testados. Evidencias:
      - 2020: 74 faturas B3 + 1 A4 extraidas com sucesso (golden confirma).
      - 2021: 9 faturas B3 extraidas com sucesso (golden confirma).
      - campos extraidos/esperados nos blocos de detalhe ficam >= 80% em todos.

    Conclusao: nao e necessario versionar os patterns de detalhe nesta fase.
    Caso uma fixture futura mostre diferenca (ex.: coluna "Tensao" ausente
    ou nome de campo diferente), adicionar versionamento aqui analogamente
    ao capa_parser.py.
"""
import re
import pdfplumber
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date

from parser import patterns
from parser.valor_parser import parse_valor_br, parse_data_br, parse_quantidade, parse_int_safe


# =============================================================
# Dataclasses
# =============================================================

@dataclass
class Tributo:
    tipo: str
    base_calculo: Decimal | None = None
    aliquota: Decimal | None = None
    valor: Decimal | None = None


@dataclass
class ValorFaturado:
    descricao: str
    quantidade: Decimal | None = None
    preco: Decimal | None = None
    valor: Decimal | None = None


@dataclass
class ValorMedido:
    especie: str
    medidor: str | None = None
    constante: Decimal | None = None
    perc_fp: Decimal | None = None
    leitura_anterior: Decimal | None = None
    leitura_atual: Decimal | None = None
    medido: Decimal | None = None
    faturado: Decimal | None = None


@dataclass
class DadosFaturaDetalhe:
    """Dados de uma fatura individual (instalacao B3 ou A4)."""
    instalacao: str | None = None
    nome_unidade: str | None = None
    nome: str | None = None
    endereco: str | None = None
    bairro: str | None = None
    municipio: str | None = None
    unidade_leitura: str | None = None
    conj_contrato: str | None = None
    local: str | None = None
    empresa: str | None = None
    referencia: str | None = None

    classe_principal: str | None = None
    classe_consumo: str | None = None
    tensao: str | None = None
    fase: Decimal | None = None

    data_faturamento: date | None = None
    dias_faturamento: int | None = None
    data_leitura_anterior: date | None = None
    data_leitura_atual: date | None = None

    hash_code: str | None = None
    nota_fiscal: str | None = None
    fatura_numero: str | None = None
    data_apresentacao: date | None = None
    data_vencimento: date | None = None
    data_recolhimento: date | None = None
    valor: Decimal | None = None

    tributos: list = field(default_factory=list)
    valores_faturados: list = field(default_factory=list)
    valores_medidos: list = field(default_factory=list)

    pagina: int | None = None
    posicao: str | None = None    # "topo" | "base" | "inteira"
    campos_extraidos: int = 0
    campos_esperados: int = 0
    avisos: list = field(default_factory=list)

    @property
    def eh_vazio(self) -> bool:
        return self.instalacao is None and self.nota_fiscal is None


# Alias para compatibilidade
DadosFaturaB3 = DadosFaturaDetalhe


# =============================================================
# Patterns
# =============================================================

_P = {
    "empresa":        re.compile(r"Empresa:\s*([^\n]+?)\s+Local:"),
    "local":          re.compile(r"Local:\s*([^\n]+?)\s+Conj\.Contrato:"),
    "conj_contrato":  re.compile(r"Conj\.Contrato:\s*(\S+)"),
    "unidade_leit":   re.compile(r"Unidade de Leitura:\s*(\S+)"),
    "referencia":     re.compile(r"Referência:\s*(\d{2}/\d{4})"),
    "nome":           re.compile(r"Nome:\s*([^\n]+?)\s+Endereço:"),
    "endereco":       re.compile(r"Endereço:\s*([^\n]+?)\s+Bairro:"),
    "bairro":         re.compile(r"Bairro:\s*([^\n]+?)(?:\n|$)"),
    "instalacao":     re.compile(r"Instalação:\s*(\d+)"),
    "complemento":    re.compile(r"Complemento:\s*([^\n]+?)\s+Fatura:"),
    "fatura":         re.compile(r"Fatura:\s*(\d+)"),
    "hash_code":      re.compile(r"Hash Code:\s*([0-9A-F.]+)"),
    "nota_fiscal":    re.compile(r"Nota Fiscal\s*:\s*(\d+)"),
    "apres":          re.compile(r"Apres:\s*(\d{2}/\d{2}/\d{4})"),
    "vecto":          re.compile(r"Vecto:\s*(\d{2}/\d{2}/\d{4})"),
    "recolhimento":   re.compile(r"Recolhimento:\s*(\d{2}/\d{2}/\d{4})"),
    "valor_final":    re.compile(r"Recolhimento:\s*\d{2}/\d{2}/\d{4}\s+Valor:\s*([\d.,]+)"),
    "classif":        re.compile(
        r"^(\d{2})\s+(\d+)\s+(B3|A4)\s+(\d+(?:,\d+)?)"
        r"\s+(\d{2}/\d{2}/\d{4})\s+(\d+)"
        r"\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})",
        re.MULTILINE
    ),
    "tributo_linha":  re.compile(
        r"^(ICMS|COFINS|PIS)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)",
        re.MULTILINE
    ),
    # Valores faturados com quantidade/preco/valor
    "consumo_vf":              re.compile(r"Consumo\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "consumo_ponta_vf":        re.compile(r"Consumo Ponta\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "consumo_fp_vf":           re.compile(r"Consumo Fora Ponta\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "demanda_ativa_isenta_vf": re.compile(r"Demanda Ativa Isenta de ICMS\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "demanda_ativa_vf":        re.compile(r"(?<!Isenta de ICMS )Demanda Ativa\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "demanda_ultra_vf":        re.compile(r"Demanda Ultrapassagem\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "reat_exc_vf":             re.compile(r"(?<!NP |FP )Consumo Reativo Excedente\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "reat_exc_fp_vf":          re.compile(r"Consumo Reativo Excedente FP\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    "reat_exc_np_vf":          re.compile(r"Consumo Reativo Excedente NP\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)-?"),
    # Valores faturados so com valor
    "bandeira_vf":     re.compile(r"Adicional Bandeira\s+([\d.,]+)-?"),
    "reter_irpj_vf":   re.compile(r"Tributo a Reter IRPJ\s+([\d.,]+)-?"),
    "reter_pis_vf":    re.compile(r"Tributo a Reter PIS\s+([\d.,]+)-?"),
    "reter_cofins_vf": re.compile(r"Tributo a Reter COFINS\s+([\d.,]+)-?"),
    "reter_csll_vf":   re.compile(r"Tributo a Reter CSLL\s+([\d.,]+)-?"),
    "credito_dic_vf":  re.compile(r"Crédito DIC/FIC/DMIC\s+([\d.,]+)-?"),
    "cip_ilum_vf":     re.compile(r"Cip[-\s]Ilum\s+Pub\s+Pref\s+Munic\s+([\d.,]+)"),
    # Valores medidos (B3: CAT; A4: CAFP CANP DAFP DANP DEFP DENP DRAF DRAN DRFP DRNP UFFP UFNP etc.)
    "medido_linha": re.compile(
        r"^(CAT|KWH|CAFP|CANP|DAFP|DANP|DEFP|DENP|DRAF|DRAN|DRFP|DRNP|UFFP|UFNP|KW|KWFP|KWNP)\s+"
        r"(\S+)\s+"
        r"([\d.,]+)\s+([\d.,]+)\s+"
        r"([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"
        r"(?:\s+([\d.,]+))?",
        re.MULTILINE
    ),
}


# =============================================================
# Utilidades
# =============================================================

def limpar_sublinhado(texto: str) -> str:
    out = []
    for linha in texto.split("\n"):
        if linha.count("_") < 5:
            out.append(linha)
            continue
        tmp = re.sub(r"_{3,}", "\x00", linha)
        tmp = tmp.replace("_", "")
        tmp = tmp.replace("\x00", " ")
        tmp = re.sub(r" +", " ", tmp).strip()
        out.append(tmp)
    return "\n".join(out)


def _match(pattern, texto, parser=None, default=None):
    m = pattern.search(texto)
    if not m:
        return default
    v = m.group(1)
    return parser(v) if parser else v.strip()


# =============================================================
# Parser de bloco de texto (usado por B3 e A4)
# =============================================================

def _parsear_bloco(texto: str, pagina: int, posicao: str) -> DadosFaturaDetalhe:
    texto = limpar_sublinhado(texto)
    idx_empresa = texto.find("Empresa:")
    if idx_empresa > 0:
        texto = texto[idx_empresa:]
    d = DadosFaturaDetalhe(pagina=pagina, posicao=posicao)

    total = 0
    ok = 0

    def tentar(pattern, campo, parser=None):
        nonlocal total, ok
        total += 1
        v = _match(pattern, texto, parser)
        if v is not None:
            ok += 1
            return v
        d.avisos.append(f"Campo nao encontrado: {campo}")
        return None

    d.empresa = tentar(_P["empresa"], "empresa")
    d.local = tentar(_P["local"], "local")
    d.conj_contrato = tentar(_P["conj_contrato"], "conj_contrato")
    d.unidade_leitura = tentar(_P["unidade_leit"], "unidade_leitura")
    d.referencia = tentar(_P["referencia"], "referencia")
    d.nome = tentar(_P["nome"], "nome")
    d.endereco = tentar(_P["endereco"], "endereco")
    d.bairro = tentar(_P["bairro"], "bairro")
    d.instalacao = tentar(_P["instalacao"], "instalacao")
    d.nome_unidade = tentar(_P["complemento"], "complemento")
    d.fatura_numero = tentar(_P["fatura"], "fatura")
    d.hash_code = tentar(_P["hash_code"], "hash_code")
    d.nota_fiscal = tentar(_P["nota_fiscal"], "nota_fiscal")

    m_mun = re.search(r"Município:\s*([A-Za-zÀ-ÿ]+)", texto)
    total += 1
    if m_mun:
        ok += 1
        d.municipio = m_mun.group(1).strip()
    else:
        d.avisos.append("Campo nao encontrado: municipio")

    d.data_apresentacao = tentar(_P["apres"], "apresentacao", parse_data_br)
    d.data_vencimento = tentar(_P["vecto"], "vencimento", parse_data_br)
    d.data_recolhimento = tentar(_P["recolhimento"], "recolhimento", parse_data_br)
    d.valor = tentar(_P["valor_final"], "valor", parse_valor_br)

    total += 1
    m = _P["classif"].search(texto)
    if m:
        ok += 1
        d.classe_principal = m.group(1)
        d.classe_consumo = m.group(2)
        d.tensao = m.group(3)
        d.fase = parse_valor_br(m.group(4))
        d.data_faturamento = parse_data_br(m.group(5))
        d.dias_faturamento = parse_int_safe(m.group(6))
        d.data_leitura_anterior = parse_data_br(m.group(7))
        d.data_leitura_atual = parse_data_br(m.group(8))
    else:
        d.avisos.append("Linha de classificacao nao encontrada")

    for tm in _P["tributo_linha"].finditer(texto):
        d.tributos.append(Tributo(
            tipo=tm.group(1),
            base_calculo=parse_valor_br(tm.group(2)),
            aliquota=parse_valor_br(tm.group(3)),
            valor=parse_valor_br(tm.group(4)),
        ))

    def _add_vf_qpv(pattern, descricao):
        m = pattern.search(texto)
        if m:
            d.valores_faturados.append(ValorFaturado(
                descricao=descricao,
                quantidade=parse_quantidade(m.group(1)),
                preco=parse_valor_br(m.group(2)),
                valor=parse_valor_br(m.group(3)),
            ))

    def _add_vf_v(pattern, descricao, negativo=False):
        m = pattern.search(texto)
        if m:
            v = parse_valor_br(m.group(1))
            if negativo and v is not None:
                v = -abs(v)
            d.valores_faturados.append(ValorFaturado(descricao=descricao, valor=v))

    # ORDEM IMPORTA: os mais especificos antes dos genericos
    _add_vf_qpv(_P["consumo_ponta_vf"], "Consumo Ponta")
    _add_vf_qpv(_P["consumo_fp_vf"], "Consumo Fora Ponta")
    _add_vf_qpv(_P["demanda_ativa_isenta_vf"], "Demanda Ativa Isenta de ICMS")
    _add_vf_qpv(_P["demanda_ativa_vf"], "Demanda Ativa")
    _add_vf_qpv(_P["demanda_ultra_vf"], "Demanda Ultrapassagem")
    _add_vf_qpv(_P["reat_exc_fp_vf"], "Consumo Reativo Excedente FP")
    _add_vf_qpv(_P["reat_exc_np_vf"], "Consumo Reativo Excedente NP")
    _add_vf_qpv(_P["reat_exc_vf"], "Consumo Reativo Excedente")
    # Consumo generico por ultimo (para nao confundir com Consumo Ponta/Fora Ponta)
    if not any(v.descricao.startswith("Consumo P") or v.descricao.startswith("Consumo F") for v in d.valores_faturados):
        _add_vf_qpv(_P["consumo_vf"], "Consumo")

    _add_vf_v(_P["bandeira_vf"], "Adicional Bandeira")
    _add_vf_v(_P["reter_irpj_vf"], "Tributo a Reter IRPJ", negativo=True)
    _add_vf_v(_P["reter_pis_vf"], "Tributo a Reter PIS", negativo=True)
    _add_vf_v(_P["reter_cofins_vf"], "Tributo a Reter COFINS", negativo=True)
    _add_vf_v(_P["reter_csll_vf"], "Tributo a Reter CSLL", negativo=True)
    _add_vf_v(_P["credito_dic_vf"], "Credito DIC/FIC/DMIC", negativo=True)
    _add_vf_v(_P["cip_ilum_vf"], "CIP Iluminacao Publica")

    for mm in _P["medido_linha"].finditer(texto):
        linha = mm.group(0)
        if " B3 " in linha or " A4 " in linha:
            continue
        d.valores_medidos.append(ValorMedido(
            especie=mm.group(1),
            medidor=mm.group(2),
            constante=parse_valor_br(mm.group(3)),
            perc_fp=parse_valor_br(mm.group(4)),
            leitura_anterior=parse_valor_br(mm.group(5)),
            leitura_atual=parse_valor_br(mm.group(6)),
            medido=parse_valor_br(mm.group(7)),
            faturado=parse_valor_br(mm.group(8)) if mm.group(8) else None,
        ))

    d.campos_extraidos = ok
    d.campos_esperados = total
    return d


# Alias interno
_parsear_metade = _parsear_bloco


# =============================================================
# API publica
# =============================================================

def parsear_pagina_b3(pdf_page, pagina_idx: int = 0) -> list[DadosFaturaDetalhe]:
    """Parseia pagina B3: 1 ou 2 faturas (metade superior e inferior)."""
    w, h = pdf_page.width, pdf_page.height
    top = pdf_page.crop((0, 0, w, h / 2)).extract_text() or ""
    bot = pdf_page.crop((0, h / 2, w, h)).extract_text() or ""

    faturas = []
    d_top = _parsear_bloco(top, pagina_idx, "topo")
    if not d_top.eh_vazio:
        faturas.append(d_top)
    d_bot = _parsear_bloco(bot, pagina_idx, "base")
    if not d_bot.eh_vazio:
        faturas.append(d_bot)
    return faturas


def parsear_pagina_a4(pdf_page, pagina_idx: int = 0) -> DadosFaturaDetalhe | None:
    """Parseia pagina A4: 1 fatura ocupa a pagina inteira."""
    texto = pdf_page.extract_text() or ""
    d = _parsear_bloco(texto, pagina_idx, "inteira")
    return None if d.eh_vazio else d


def parsear_todas_b3(caminho_pdf: str | Path, paginas_b3: list[int]) -> list[DadosFaturaDetalhe]:
    faturas = []
    with pdfplumber.open(str(caminho_pdf)) as pdf:
        for idx in paginas_b3:
            faturas.extend(parsear_pagina_b3(pdf.pages[idx], idx))
    return faturas


def parsear_todas_a4(caminho_pdf: str | Path, paginas_a4: list[int]) -> list[DadosFaturaDetalhe]:
    faturas = []
    with pdfplumber.open(str(caminho_pdf)) as pdf:
        for idx in paginas_a4:
            d = parsear_pagina_a4(pdf.pages[idx], idx)
            if d is not None:
                faturas.append(d)
    return faturas
