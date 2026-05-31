"""
Views analiticas (Power BI) em sintaxe SQLite.

Porte das 7 views originalmente definidas em PostgreSQL
(db/migrations/001_initial.sql). Mantem EXATAMENTE os mesmos nomes de view
e de coluna — o export/powerbi.py e o Power BI dependem disso.

Diferencas de dialeto tratadas aqui:
  - EXTRACT(... FROM data)::INT   ->  CAST(strftime('%Y'|'%m'|'%d', data) AS INTEGER)
  - TO_CHAR(data, 'YYYY-MM')      ->  strftime('%Y-%m', data)
  - TO_CHAR(data, 'TMMonth'/'TMDY') -> CASE sobre strftime('%m'/'%w', data) em PT-BR
  - EXTRACT(QUARTER FROM data)    ->  (CAST(strftime('%m', data) AS INTEGER) + 2) / 3
  - generate_series(d1, d2, '1 day') -> CTE recursiva (WITH RECURSIVE dias)
  - BOOLEAN TRUE/FALSE            ->  1 / 0 (representacao booleana do SQLite)

As funcoes RANK() OVER e ORDER BY ... DESC sao mantidas: o SQLite >= 3.25
suporta window functions nativamente.

Uso:
    from db.views_sqlite import criar_views_sqlite
    criar_views_sqlite(engine)   # idempotente (DROP + CREATE)
"""
from __future__ import annotations

# Cada entrada: (nome_da_view, corpo_SELECT). A view e recriada (DROP + CREATE)
# a cada init_db() para garantir que a definicao acompanhe atualizacoes do app.
VIEWS: list[tuple[str, str]] = []


# =============================================================
# VIEW PRINCIPAL: Fato consumo por unidade
# =============================================================
VIEWS.append(("vw_fato_consumo", """
SELECT
    fi.id                           AS fatura_id,
    fa.id                           AS agrupadora_id,
    fi.instalacao,
    fi.nota_fiscal,

    -- Tempo
    fa.referencia,
    fa.vencimento,
    fi.data_faturamento,
    fi.dias_faturamento,
    CAST(strftime('%Y', fa.vencimento) AS INTEGER)  AS ano,
    CAST(strftime('%m', fa.vencimento) AS INTEGER)  AS mes,
    strftime('%Y-%m', fa.vencimento)                AS ano_mes,

    -- Localizacao
    fi.nome_unidade,
    fi.endereco,
    fi.bairro,
    fi.municipio,

    -- Tecnica
    fi.tensao,
    fi.fase,
    fi.classe_principal,
    fi.unidade_leitura,

    -- Agrupadora
    fa.complemento                  AS grupo_semed,
    fa.documento                    AS doc_agrupadora,
    fa.status                       AS status_importacao,

    -- Valor
    fi.valor                        AS valor_fatura,

    -- Consumo
    COALESCE(consumo.quantidade, 0)     AS kwh_consumo,
    COALESCE(consumo.valor, 0)          AS valor_consumo,
    COALESCE(consumo.preco, 0)          AS tarifa_consumo,

    -- Ponta (A4)
    COALESCE(ponta.quantidade, 0)       AS kwh_ponta,
    COALESCE(ponta.valor, 0)            AS valor_ponta,

    -- Fora Ponta (A4)
    COALESCE(fora_ponta.quantidade, 0)  AS kwh_fora_ponta,
    COALESCE(fora_ponta.valor, 0)       AS valor_fora_ponta,

    -- Demanda
    COALESCE(demanda.quantidade, 0)     AS kw_demanda,
    COALESCE(demanda.valor, 0)          AS valor_demanda,

    -- Ultrapassagem (multa)
    COALESCE(ultra.quantidade, 0)       AS kw_ultrapassagem,
    COALESCE(ultra.valor, 0)            AS valor_ultrapassagem,

    -- Bandeira
    COALESCE(bandeira.valor, 0)         AS valor_bandeira,

    -- Tributos
    COALESCE(t_icms.valor, 0)           AS icms,
    COALESCE(t_cofins.valor, 0)         AS cofins,
    COALESCE(t_pis.valor, 0)            AS pis,
    COALESCE(t_icms.valor, 0)
        + COALESCE(t_cofins.valor, 0)
        + COALESCE(t_pis.valor, 0)      AS total_tributos,

    -- Retencoes
    COALESCE(ret_irpj.valor, 0)         AS retencao_irpj,
    COALESCE(ret_csll.valor, 0)         AS retencao_csll,
    COALESCE(ret_pis.valor, 0)          AS retencao_pis,
    COALESCE(ret_cofins.valor, 0)       AS retencao_cofins,

    -- Reativos
    COALESCE(reat_fp.quantidade, 0)     AS reat_exc_fp_qtd,
    COALESCE(reat_fp.valor, 0)          AS reat_exc_fp_valor,
    COALESCE(reat_np.quantidade, 0)     AS reat_exc_np_qtd,
    COALESCE(reat_np.valor, 0)          AS reat_exc_np_valor,

    -- Calculados
    CASE WHEN COALESCE(consumo.quantidade, 0) > 0
         THEN fi.valor / consumo.quantidade
         ELSE NULL
    END                                 AS custo_por_kwh,

    CASE WHEN fi.valor > 0
         THEN (COALESCE(t_icms.valor,0) + COALESCE(t_cofins.valor,0)
               + COALESCE(t_pis.valor,0)) / fi.valor * 100
         ELSE 0
    END                                 AS perc_tributos

FROM fatura_individual fi
JOIN fatura_agrupadora fa ON fi.agrupadora_id = fa.id
LEFT JOIN valor_faturado consumo     ON consumo.fatura_individual_id = fi.id     AND consumo.descricao = 'Consumo'
LEFT JOIN valor_faturado ponta       ON ponta.fatura_individual_id = fi.id       AND ponta.descricao = 'Consumo Ponta'
LEFT JOIN valor_faturado fora_ponta  ON fora_ponta.fatura_individual_id = fi.id  AND fora_ponta.descricao = 'Consumo Fora Ponta'
LEFT JOIN valor_faturado demanda     ON demanda.fatura_individual_id = fi.id     AND demanda.descricao = 'Demanda Ativa'
LEFT JOIN valor_faturado ultra       ON ultra.fatura_individual_id = fi.id       AND ultra.descricao = 'Demanda Ultrapassagem'
LEFT JOIN valor_faturado bandeira    ON bandeira.fatura_individual_id = fi.id    AND bandeira.descricao = 'Adicional Bandeira'
LEFT JOIN valor_faturado ret_irpj    ON ret_irpj.fatura_individual_id = fi.id    AND ret_irpj.descricao = 'Tributo a Reter IRPJ'
LEFT JOIN valor_faturado ret_csll    ON ret_csll.fatura_individual_id = fi.id    AND ret_csll.descricao = 'Tributo a Reter CSLL'
LEFT JOIN valor_faturado ret_pis     ON ret_pis.fatura_individual_id = fi.id     AND ret_pis.descricao = 'Tributo a Reter PIS'
LEFT JOIN valor_faturado ret_cofins  ON ret_cofins.fatura_individual_id = fi.id  AND ret_cofins.descricao = 'Tributo a Reter COFINS'
LEFT JOIN valor_faturado reat_fp     ON reat_fp.fatura_individual_id = fi.id     AND reat_fp.descricao LIKE 'Consumo Reativo Excedente FP%'
LEFT JOIN valor_faturado reat_np     ON reat_np.fatura_individual_id = fi.id     AND reat_np.descricao LIKE 'Consumo Reativo Excedente NP%'
LEFT JOIN tributo t_icms             ON t_icms.fatura_individual_id = fi.id      AND t_icms.tipo = 'ICMS'
LEFT JOIN tributo t_cofins           ON t_cofins.fatura_individual_id = fi.id    AND t_cofins.tipo = 'COFINS'
LEFT JOIN tributo t_pis              ON t_pis.fatura_individual_id = fi.id       AND t_pis.tipo = 'PIS'
"""))


# =============================================================
# VIEW: Resumo mensal por grupo SEMED
# =============================================================
VIEWS.append(("vw_resumo_mensal", """
SELECT
    fa.referencia,
    fa.complemento                  AS grupo_semed,
    fa.vencimento,
    CAST(strftime('%Y', fa.vencimento) AS INTEGER) AS ano,
    CAST(strftime('%m', fa.vencimento) AS INTEGER) AS mes,
    fa.valor_total,
    fa.qtd_faturas_esperada         AS total_unidades,
    fa.consumo_qtd                  AS kwh_total,
    fa.consumo_valor                AS valor_consumo,
    fa.icms_total,
    fa.cofins_total,
    fa.pis_total,
    fa.adicional_bandeira,
    fa.demanda_ativa_valor,
    fa.demanda_ultra_valor          AS valor_ultrapassagem,
    fa.trib_reter_irpj,
    fa.status,
    fa.documento
FROM fatura_agrupadora fa
"""))


# =============================================================
# VIEW: Ranking de consumo por unidade
# =============================================================
VIEWS.append(("vw_ranking_unidades", """
SELECT
    fi.instalacao,
    fi.nome_unidade,
    fi.bairro,
    fi.tensao,
    fa.referencia,
    fa.complemento                  AS grupo_semed,
    fi.valor,
    COALESCE(consumo.quantidade, 0) AS kwh,
    CASE WHEN COALESCE(consumo.quantidade, 0) > 0
         THEN fi.valor / consumo.quantidade
         ELSE NULL
    END                             AS custo_kwh,
    COALESCE(ultra.valor, 0)        AS multa_ultrapassagem,
    RANK() OVER (
        PARTITION BY fa.referencia
        ORDER BY fi.valor DESC
    )                               AS ranking_valor
FROM fatura_individual fi
JOIN fatura_agrupadora fa ON fi.agrupadora_id = fa.id
LEFT JOIN valor_faturado consumo ON consumo.fatura_individual_id = fi.id AND consumo.descricao = 'Consumo'
LEFT JOIN valor_faturado ultra   ON ultra.fatura_individual_id = fi.id   AND ultra.descricao = 'Demanda Ultrapassagem'
"""))


# =============================================================
# VIEW: Leituras dos medidores
# =============================================================
VIEWS.append(("vw_leituras", """
SELECT
    fi.instalacao,
    fi.nome_unidade,
    fi.tensao,
    fa.referencia,
    fa.complemento                  AS grupo_semed,
    vm.especie,
    vm.medidor,
    vm.constante,
    vm.perc_fp,
    vm.leitura_anterior,
    vm.leitura_atual,
    vm.medido,
    vm.faturado,
    fi.data_leitura_anterior,
    fi.data_leitura_atual,
    fi.dias_faturamento
FROM valor_medido vm
JOIN fatura_individual fi ON vm.fatura_individual_id = fi.id
JOIN fatura_agrupadora fa ON fi.agrupadora_id = fa.id
"""))


# =============================================================
# VIEW: Tributos detalhados
# =============================================================
VIEWS.append(("vw_tributos_detalhado", """
SELECT
    fi.instalacao,
    fi.nome_unidade,
    fi.bairro,
    fa.referencia,
    fa.complemento                  AS grupo_semed,
    fi.valor                        AS valor_fatura,
    t.tipo                          AS tributo,
    t.base_calculo,
    t.aliquota,
    t.valor                         AS valor_tributo,
    CASE WHEN fi.valor > 0
         THEN t.valor / fi.valor * 100
         ELSE 0
    END                             AS perc_sobre_fatura
FROM tributo t
JOIN fatura_individual fi ON t.fatura_individual_id = fi.id
JOIN fatura_agrupadora fa ON fi.agrupadora_id = fa.id
"""))


# =============================================================
# VIEW: Controle de importacoes
# =============================================================
VIEWS.append(("vw_controle_importacao", """
SELECT
    fa.documento,
    fa.complemento                  AS grupo_semed,
    fa.referencia,
    fa.status,
    fa.qtd_faturas_esperada,
    fa.faturas_importadas,
    fa.faturas_com_erro,
    fa.importado_em,
    fa.arquivo_origem,
    ap.hash_sha256,
    ap.nome_original                AS arquivo_original,
    ap.nome_padronizado             AS arquivo_renomeado,
    ap.resultado                    AS resultado_arquivo,
    CASE WHEN fa.faturas_com_erro > 0
         THEN fa.erros_log
         ELSE NULL
    END                             AS erros
FROM fatura_agrupadora fa
LEFT JOIN arquivo_processado ap ON ap.agrupadora_id = fa.id
ORDER BY fa.importado_em DESC
"""))


# =============================================================
# DIMENSAO: Calendario brasileiro (CTE recursiva no lugar de generate_series)
# =============================================================
VIEWS.append(("vw_dim_calendario", """
WITH RECURSIVE dias(d) AS (
    SELECT date('2020-01-01')
    UNION ALL
    SELECT date(d, '+1 day') FROM dias WHERE d < '2030-12-31'
)
SELECT
    d                                           AS data,
    CAST(strftime('%Y', d) AS INTEGER)          AS ano,
    CAST(strftime('%m', d) AS INTEGER)          AS mes,
    CAST(strftime('%d', d) AS INTEGER)          AS dia,
    strftime('%Y-%m', d)                        AS ano_mes,
    CASE strftime('%m', d)
        WHEN '01' THEN 'Janeiro'   WHEN '02' THEN 'Fevereiro'
        WHEN '03' THEN 'Março'     WHEN '04' THEN 'Abril'
        WHEN '05' THEN 'Maio'      WHEN '06' THEN 'Junho'
        WHEN '07' THEN 'Julho'     WHEN '08' THEN 'Agosto'
        WHEN '09' THEN 'Setembro'  WHEN '10' THEN 'Outubro'
        WHEN '11' THEN 'Novembro'  WHEN '12' THEN 'Dezembro'
    END                                         AS nome_mes,
    CASE strftime('%w', d)
        WHEN '0' THEN 'Dom' WHEN '1' THEN 'Seg' WHEN '2' THEN 'Ter'
        WHEN '3' THEN 'Qua' WHEN '4' THEN 'Qui' WHEN '5' THEN 'Sex'
        WHEN '6' THEN 'Sáb'
    END                                         AS dia_semana,
    (CAST(strftime('%m', d) AS INTEGER) + 2) / 3            AS trimestre,
    'T' || ((CAST(strftime('%m', d) AS INTEGER) + 2) / 3)  AS trimestre_label,
    CAST(strftime('%W', d) AS INTEGER)          AS semana_ano,
    CASE WHEN CAST(strftime('%m', d) AS INTEGER) <= 6 THEN 1 ELSE 2
    END                                         AS semestre,
    CASE WHEN CAST(strftime('%m', d) AS INTEGER) BETWEEN 5 AND 11 THEN 1 ELSE 0
    END                                         AS estacao_seca,
    CASE WHEN CAST(strftime('%m', d) AS INTEGER) IN (12, 1, 2, 3, 4) THEN 1 ELSE 0
    END                                         AS estacao_chuvosa,
    CASE WHEN CAST(strftime('%m', d) AS INTEGER) BETWEEN 5 AND 11
         THEN 'Seca (Mai-Nov)'
         ELSE 'Chuvosa (Dez-Abr)'
    END                                         AS periodo_hidrologico
FROM dias
"""))


def criar_views_sqlite(engine) -> None:
    """
    (Re)cria as 7 views analiticas no banco SQLite, de forma idempotente.

    Faz DROP VIEW IF EXISTS + CREATE VIEW para cada uma, garantindo que a
    definicao acompanhe atualizacoes do app (uma simples CREATE IF NOT EXISTS
    nao atualizaria views ja existentes apos um update).
    """
    from sqlalchemy import text
    with engine.begin() as conn:
        for nome, corpo in VIEWS:
            conn.execute(text(f"DROP VIEW IF EXISTS {nome}"))
            conn.execute(text(f"CREATE VIEW {nome} AS {corpo}"))
