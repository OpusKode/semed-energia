"""
Detecta o layout da fatura Equatorial a partir do texto extraído da capa.
Retorna uma string literal: "v2020" | "v2022" | "v2026"

Decisão de design: a detecção é feita por auto-detecção interna ao
`parsear_texto_capa`; não há parâmetro externo `versao` na API pública.
Isso simplifica o caller e evita erros de passagem de argumento errado.

Nota sobre "DISTRIB. DE ENERGIA S.A.":
O plano original listava "DISTRIB. DE ENERGIA S.A." como marcador v2020.
Após inspecionar os fixtures, essa string aparece em 2020, 2021, 2022 E
2023 — portanto NÃO é confiável para distinguir versões de parser.
Usamos apenas os campos antigos de encargos por atraso como marcadores.
"""
from typing import Literal
import re

VersaoLayout = Literal["v2020", "v2022", "v2026"]

# v2020/v2021: bandeira tarifária separada em "Adicional Band. Amarela" /
# "Adicional Band. Vermelha" — exclusivo do layout antigo.
#
# NÃO usamos "Correção Monetária" como marcador porque faturas modernas
# (ex.: 2025 Julho) podem ter encargos por atraso com o mesmo campo —
# a presença de "Correção Monetária" é consequência do histórico de
# pagamento do cliente, não do layout da fatura.
# NÃO usamos "DISTRIB. DE ENERGIA S.A." porque aparece em 2022 e 2023
# com layout moderno (DISTRIBUIDORA só muda para DISTRIBUIDORA em ~2026).
_MARCA_V2020 = re.compile(
    r"Adicional Band\. (?:Amarela|Vermelha)",
    re.IGNORECASE,
)

# v2022+: crédito de devolução ICMS LC 194/2022 (lei publicada ago/2022)
_MARCA_V2022 = re.compile(r"Devolução ICMS LC 194/22", re.IGNORECASE)


def detectar_versao(texto: str) -> VersaoLayout:
    """
    Determina a versão de layout da fatura a partir do texto da capa.

    Heurística (ordem importa — v2020 tem precedência):

    1. "Adicional Band. Amarela" OU "Adicional Band. Vermelha"  → v2020
       Marcador exclusivo do layout 2020-2021: a bandeira tarifária é
       discriminada por cor (amarela / vermelha) em vez de um valor único
       "Adicional Bandeira". "Correção Monetária", "Multa" e "Juros" também
       existem nesse layout, porém NÃO são usados como marcadores porque
       aparecem igualmente em faturas modernas com débito anterior
       (ex.: 2025-Julho que tem "Correção Monetária: R$ 4,03").

    2. "Devolução ICMS LC 194/22"  → v2022
       Crédito de devolução ICMS instituído pela LC 194/2022; só aparece
       em faturas emitidas a partir do 2º semestre de 2022.

    3. Default  → v2026
       Layout moderno (referência dos parsers originais).

    Args:
        texto: texto extraído da primeira página do PDF (via fitz).

    Returns:
        "v2020", "v2022" ou "v2026".
    """
    if _MARCA_V2020.search(texto):
        return "v2020"
    if _MARCA_V2022.search(texto):
        return "v2022"
    return "v2026"
