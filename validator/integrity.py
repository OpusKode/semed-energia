"""
Validacao de integridade em 3 camadas:

1. Estrutural  — CNPJ, concessionaria, contagem, completude
2. Matematica  — tributos (base x aliquota = valor), consumo (q x p = v),
                total (SUM(individual.valor) = agrupadora.valor_total)
3. Semantica   — aliquota ICMS-PA, plausibilidade, datas coerentes

A API publica principal e `validar_tudo(capa, faturas)` que recebe os
dataclasses ja populados pelos parsers e devolve um ResumoValidacao
com listas separadas de erros, warnings e infos.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from typing import Iterable

try:
    from validate_docbr import CNPJ
    _CNPJ_VALIDATOR = CNPJ()
except Exception:  # pragma: no cover
    _CNPJ_VALIDATOR = None


# =============================================================
# Constantes
# =============================================================

TOLERANCIA_ITEM = Decimal("0.02")        # R$ 0,02 por item individual
TOLERANCIA_TOTAL = Decimal("0.05")       # R$ 0,05 para total da agrupadora
ALIQUOTA_ICMS_PA = Decimal("19.00")      # aliquota esperada no Para
TOLERANCIA_ALIQUOTA = Decimal("0.50")    # +- 0,5 pontos percentuais

# Faixas de plausibilidade
CONSUMO_MIN = Decimal("0")
CONSUMO_MAX = Decimal("100000")          # kWh por instalacao
VALOR_FATURA_MIN = Decimal("0")
VALOR_FATURA_MAX = Decimal("50000")      # R$ por fatura individual
DIAS_FAT_MIN = 25
DIAS_FAT_MAX = 35

CENT = Decimal("0.01")


# =============================================================
# Dataclasses de resultado
# =============================================================

@dataclass
class Resultado:
    """Resultado de uma validacao isolada."""
    camada: int                          # 1, 2 ou 3
    tipo: str                            # identificador (ex 'icms', 'cnpj')
    resultado: str                       # 'OK' | 'WARN' | 'ERRO'
    mensagem: str = ""
    valor_esperado: Decimal | None = None
    valor_encontrado: Decimal | None = None
    diferenca: Decimal | None = None
    fatura_nota: str | None = None       # nota fiscal da fatura afetada, se aplicavel

    @property
    def eh_erro(self) -> bool:
        return self.resultado == "ERRO"

    @property
    def eh_warning(self) -> bool:
        return self.resultado == "WARN"


@dataclass
class ResumoValidacao:
    resultados: list = field(default_factory=list)

    def add(self, r: Resultado):
        self.resultados.append(r)

    @property
    def erros(self) -> list:
        return [r for r in self.resultados if r.eh_erro]

    @property
    def warnings(self) -> list:
        return [r for r in self.resultados if r.eh_warning]

    @property
    def oks(self) -> list:
        return [r for r in self.resultados if r.resultado == "OK"]

    @property
    def pode_persistir(self) -> bool:
        """Se nao ha erros estruturais (camada 1), a persistencia e OK."""
        return not any(r.eh_erro for r in self.resultados)

    def estatisticas(self) -> dict:
        return {
            "total": len(self.resultados),
            "ok": len(self.oks),
            "warn": len(self.warnings),
            "erro": len(self.erros),
            "por_camada": {
                c: sum(1 for r in self.resultados if r.camada == c)
                for c in (1, 2, 3)
            },
        }


# =============================================================
# Camada 1 — Validacao estrutural
# =============================================================

def validar_cnpj(cnpj: str | None) -> Resultado:
    if not cnpj:
        return Resultado(1, "cnpj", "ERRO", "CNPJ ausente na capa")
    if _CNPJ_VALIDATOR is None:
        return Resultado(1, "cnpj", "WARN",
                         "Biblioteca validate-docbr indisponivel; validacao pulada")
    if _CNPJ_VALIDATOR.validate(cnpj):
        return Resultado(1, "cnpj", "OK", f"CNPJ {cnpj} valido")
    return Resultado(1, "cnpj", "ERRO", f"CNPJ {cnpj} invalido (digito verificador)")


def validar_concessionaria(eh_equatorial: bool) -> Resultado:
    if eh_equatorial:
        return Resultado(1, "concessionaria", "OK", "Concessionaria EQUATORIAL PARA")
    return Resultado(1, "concessionaria", "ERRO",
                     "Concessionaria nao e Equatorial Para — arquivo rejeitado")


def validar_contagem_faturas(qtd_esperada: int | None,
                              qtd_importada: int,
                              qtd_erro: int = 0) -> Resultado:
    if qtd_esperada is None:
        return Resultado(2, "contagem", "WARN",
                         "Quantidade esperada nao foi extraida da capa")
    total_processado = qtd_importada + qtd_erro
    if total_processado == qtd_esperada:
        return Resultado(2, "contagem", "OK",
                         f"Contagem OK: {qtd_importada} importadas + {qtd_erro} erros = {qtd_esperada} esperadas")
    return Resultado(
        2, "contagem", "WARN",
        f"Contagem divergente: {qtd_importada} importadas + {qtd_erro} erros != {qtd_esperada} esperadas",
        valor_esperado=Decimal(qtd_esperada),
        valor_encontrado=Decimal(total_processado),
        diferenca=Decimal(abs(qtd_esperada - total_processado)),
    )


def validar_completude_fatura(fatura) -> Resultado:
    """Fatura individual deve ter >= 1 tributo e >= 1 valor_faturado."""
    problemas = []
    if not fatura.tributos:
        problemas.append("sem tributos")
    if not fatura.valores_faturados:
        problemas.append("sem valores faturados")
    if problemas:
        return Resultado(
            1, "completude", "WARN",
            f"Fatura {fatura.nota_fiscal} incompleta: {', '.join(problemas)}",
            fatura_nota=fatura.nota_fiscal,
        )
    return Resultado(1, "completude", "OK",
                     f"Fatura {fatura.nota_fiscal} completa",
                     fatura_nota=fatura.nota_fiscal)


# =============================================================
# Camada 2 — Validacao matematica
# =============================================================

def _q2(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def validar_tributo(base: Decimal | None, aliquota: Decimal | None,
                    valor: Decimal | None, tipo: str,
                    fatura_nota: str | None = None) -> Resultado:
    """Valida: base x (aliquota/100) ~= valor, tolerancia R$ 0,02."""
    if base is None or aliquota is None or valor is None:
        return Resultado(2, f"trib_{tipo.lower()}", "WARN",
                         f"Tributo {tipo} com campo ausente",
                         fatura_nota=fatura_nota)
    calculado = _q2(base * aliquota / Decimal("100"))
    dif = abs(calculado - valor)
    if dif <= TOLERANCIA_ITEM:
        return Resultado(2, f"trib_{tipo.lower()}", "OK",
                         f"{tipo}: {base} x {aliquota}% = {calculado} ~= {valor}",
                         valor_esperado=calculado, valor_encontrado=valor,
                         diferenca=dif, fatura_nota=fatura_nota)
    return Resultado(2, f"trib_{tipo.lower()}", "WARN",
                     f"{tipo} divergente: calc={calculado} extraido={valor} dif={dif}",
                     valor_esperado=calculado, valor_encontrado=valor,
                     diferenca=dif, fatura_nota=fatura_nota)


def validar_consumo(quantidade: Decimal | None, preco: Decimal | None,
                    valor: Decimal | None, descricao: str,
                    fatura_nota: str | None = None) -> Resultado:
    """Valida: quantidade x preco ~= valor, tolerancia R$ 0,02."""
    if quantidade is None or preco is None or valor is None:
        return Resultado(2, "consumo", "WARN",
                         f"{descricao}: campo ausente (q={quantidade} p={preco} v={valor})",
                         fatura_nota=fatura_nota)
    calculado = _q2(quantidade * preco)
    dif = abs(calculado - valor)
    if dif <= TOLERANCIA_ITEM:
        return Resultado(2, "consumo", "OK",
                         f"{descricao}: {quantidade} x {preco} = {calculado} ~= {valor}",
                         valor_esperado=calculado, valor_encontrado=valor,
                         diferenca=dif, fatura_nota=fatura_nota)
    return Resultado(2, "consumo", "WARN",
                     f"{descricao} divergente: calc={calculado} extraido={valor} dif={dif}",
                     valor_esperado=calculado, valor_encontrado=valor,
                     diferenca=dif, fatura_nota=fatura_nota)


def validar_adicional_bandeira(
    adicional_bandeira: Decimal | None,
    bandeira_amarela: Decimal | None,
    bandeira_vermelha: Decimal | None,
) -> Resultado | None:
    """
    Validação cruzada do adicional de bandeira tarifária.

    Layout v2026: `adicional_bandeira` é um valor único — sem verificação
    cruzada possível (retorna None, indicando que não há regra aplicável).

    Layout v2020: `bandeira_amarela` e/ou `bandeira_vermelha` devem somar
    ao `adicional_bandeira` (se este também estiver preenchido). Usa a mesma
    tolerância de R$ 0,02 das demais validações matemáticas.

    Returns:
        Resultado de validação, ou None se a regra não se aplica.
    """
    tem_historica = (bandeira_amarela is not None) or (bandeira_vermelha is not None)
    if not tem_historica:
        # Layout moderno: sem bandeiras separadas — regra não se aplica
        return None

    soma = (bandeira_amarela or Decimal("0")) + (bandeira_vermelha or Decimal("0"))

    if adicional_bandeira is None:
        # Bandeiras históricas presentes mas sem adicional_bandeira para cruzar;
        # informa como aviso (pode ser normal em alguns meses sem penalidade)
        return Resultado(
            2, "bandeira_historica", "WARN",
            f"bandeira_amarela={bandeira_amarela} bandeira_vermelha={bandeira_vermelha} "
            f"mas adicional_bandeira ausente (normal se não houve cobranças no mês)",
            valor_esperado=soma,
            valor_encontrado=None,
        )

    dif = abs(soma - adicional_bandeira)
    if dif <= TOLERANCIA_ITEM:
        return Resultado(
            2, "bandeira_historica", "OK",
            f"Bandeira OK: amarela={bandeira_amarela} + vermelha={bandeira_vermelha} "
            f"= {soma} ~= adicional_bandeira={adicional_bandeira}",
            valor_esperado=soma,
            valor_encontrado=adicional_bandeira,
            diferenca=dif,
        )
    return Resultado(
        2, "bandeira_historica", "WARN",
        f"Bandeira divergente: amarela={bandeira_amarela} + vermelha={bandeira_vermelha} "
        f"= {soma} != adicional_bandeira={adicional_bandeira} (dif={dif})",
        valor_esperado=soma,
        valor_encontrado=adicional_bandeira,
        diferenca=dif,
    )


def validar_total_agrupadora(soma_individuais: Decimal,
                              total_capa: Decimal | None) -> Resultado:
    if total_capa is None:
        return Resultado(2, "total", "WARN",
                         "valor_total da capa ausente — validacao pulada")
    dif = abs(soma_individuais - total_capa)
    if dif <= TOLERANCIA_TOTAL:
        return Resultado(2, "total", "OK",
                         f"Total bate: soma={soma_individuais} capa={total_capa}",
                         valor_esperado=total_capa, valor_encontrado=soma_individuais,
                         diferenca=dif)
    return Resultado(2, "total", "WARN",
                     f"Total divergente: soma={soma_individuais} capa={total_capa} dif={dif}",
                     valor_esperado=total_capa, valor_encontrado=soma_individuais,
                     diferenca=dif)


# =============================================================
# Camada 3 — Validacao semantica
# =============================================================

def validar_aliquota_icms(aliquota: Decimal | None,
                          fatura_nota: str | None = None) -> Resultado:
    if aliquota is None:
        return Resultado(3, "aliquota_icms", "WARN",
                         "Aliquota ICMS ausente", fatura_nota=fatura_nota)
    dif = abs(aliquota - ALIQUOTA_ICMS_PA)
    if dif <= TOLERANCIA_ALIQUOTA:
        return Resultado(3, "aliquota_icms", "OK",
                         f"Aliquota ICMS {aliquota}% dentro do esperado ({ALIQUOTA_ICMS_PA}%)",
                         valor_esperado=ALIQUOTA_ICMS_PA, valor_encontrado=aliquota,
                         diferenca=dif, fatura_nota=fatura_nota)
    return Resultado(3, "aliquota_icms", "WARN",
                     f"Aliquota ICMS {aliquota}% fora do padrao PA ({ALIQUOTA_ICMS_PA}%)",
                     valor_esperado=ALIQUOTA_ICMS_PA, valor_encontrado=aliquota,
                     diferenca=dif, fatura_nota=fatura_nota)


def validar_plausibilidade_valor(valor: Decimal | None,
                                  fatura_nota: str | None = None) -> Resultado:
    if valor is None:
        return Resultado(3, "valor_plausivel", "WARN",
                         "Valor da fatura ausente", fatura_nota=fatura_nota)
    if VALOR_FATURA_MIN <= valor <= VALOR_FATURA_MAX:
        return Resultado(3, "valor_plausivel", "OK",
                         f"Valor R$ {valor} na faixa plausivel",
                         fatura_nota=fatura_nota)
    return Resultado(3, "valor_plausivel", "WARN",
                     f"Valor R$ {valor} fora da faixa plausivel "
                     f"[{VALOR_FATURA_MIN}, {VALOR_FATURA_MAX}]",
                     fatura_nota=fatura_nota)


def validar_datas_leitura(data_ant: date | None, data_atu: date | None,
                          fatura_nota: str | None = None) -> Resultado:
    if data_ant is None or data_atu is None:
        return Resultado(3, "datas", "WARN",
                         "Datas de leitura ausentes", fatura_nota=fatura_nota)
    if data_atu > data_ant:
        return Resultado(3, "datas", "OK",
                         f"Leitura: {data_ant} -> {data_atu}",
                         fatura_nota=fatura_nota)
    return Resultado(3, "datas", "WARN",
                     f"Datas invertidas: anterior={data_ant} atual={data_atu}",
                     fatura_nota=fatura_nota)


def validar_dias_faturamento(dias: int | None,
                              fatura_nota: str | None = None) -> Resultado:
    if dias is None:
        return Resultado(3, "dias_fat", "WARN",
                         "Dias de faturamento ausentes", fatura_nota=fatura_nota)
    if DIAS_FAT_MIN <= dias <= DIAS_FAT_MAX:
        return Resultado(3, "dias_fat", "OK",
                         f"{dias} dias de faturamento",
                         fatura_nota=fatura_nota)
    return Resultado(3, "dias_fat", "WARN",
                     f"Dias de faturamento fora da faixa: {dias} "
                     f"(esperado {DIAS_FAT_MIN}-{DIAS_FAT_MAX})",
                     fatura_nota=fatura_nota)


# =============================================================
# Orquestrador
# =============================================================

def _somar_consumos(fatura) -> Decimal:
    """Soma quantidade de todas as entradas de consumo (kWh)."""
    total = Decimal("0")
    for v in fatura.valores_faturados:
        if v.descricao and v.descricao.startswith("Consumo") and v.quantidade:
            total += v.quantidade
    return total


def validar_fatura_individual(fatura) -> list:
    """Executa todas as validacoes de uma fatura individual."""
    out = []
    out.append(validar_completude_fatura(fatura))

    for t in fatura.tributos:
        out.append(validar_tributo(t.base_calculo, t.aliquota, t.valor,
                                   t.tipo, fatura.nota_fiscal))
        if t.tipo == "ICMS":
            out.append(validar_aliquota_icms(t.aliquota, fatura.nota_fiscal))

    for v in fatura.valores_faturados:
        if v.quantidade is not None and v.preco is not None and v.valor is not None:
            out.append(validar_consumo(v.quantidade, v.preco, v.valor,
                                       v.descricao, fatura.nota_fiscal))

    out.append(validar_plausibilidade_valor(fatura.valor, fatura.nota_fiscal))
    out.append(validar_datas_leitura(fatura.data_leitura_anterior,
                                     fatura.data_leitura_atual, fatura.nota_fiscal))
    out.append(validar_dias_faturamento(fatura.dias_faturamento, fatura.nota_fiscal))

    return out


def validar_tudo(capa, faturas: Iterable,
                 eh_equatorial: bool = True) -> ResumoValidacao:
    """
    Ponto de entrada: recebe DadosCapa e lista de DadosFaturaDetalhe e
    devolve ResumoValidacao com todas as verificacoes agregadas.
    """
    resumo = ResumoValidacao()

    # Camada 1: estrutural na capa
    resumo.add(validar_concessionaria(eh_equatorial))
    resumo.add(validar_cnpj(capa.cliente_cnpj))

    faturas = list(faturas)

    # Camada 2: contagem
    resumo.add(validar_contagem_faturas(capa.qtd_faturas_esperada,
                                         qtd_importada=len(faturas)))

    # Camada 2: total agrupadora
    soma = sum((f.valor or Decimal("0")) for f in faturas)
    resumo.add(validar_total_agrupadora(soma, capa.valor_total))

    # Camada 2: bandeira histórica (v2020 — bandeira_amarela + bandeira_vermelha)
    r_bandeira = validar_adicional_bandeira(
        getattr(capa, "adicional_bandeira", None),
        getattr(capa, "bandeira_amarela", None),
        getattr(capa, "bandeira_vermelha", None),
    )
    if r_bandeira is not None:
        resumo.add(r_bandeira)

    # Por fatura individual (camadas 1-3)
    for f in faturas:
        for r in validar_fatura_individual(f):
            resumo.add(r)

    return resumo
