-- =============================================
-- SEMED Energia — Migração Inicial
-- Versão: 3.0
-- Data: 2026-04-15
-- =============================================

BEGIN;

-- =============================================
-- TABELA: Controle de arquivos processados
-- =============================================
CREATE TABLE IF NOT EXISTS arquivo_processado (
    id              SERIAL PRIMARY KEY,
    nome_original   VARCHAR(500) NOT NULL,
    nome_padronizado VARCHAR(500),
    hash_sha256     VARCHAR(64) NOT NULL UNIQUE,
    tamanho_bytes   BIGINT,
    documento       VARCHAR(20),
    agrupadora_id   INTEGER,
    processado_em   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resultado       VARCHAR(20) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_arq_hash ON arquivo_processado(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_arq_documento ON arquivo_processado(documento);


-- =============================================
-- TABELA: Fatura agrupadora (1 por PDF)
-- =============================================
CREATE TABLE IF NOT EXISTS fatura_agrupadora (
    id                      SERIAL PRIMARY KEY,
    documento               VARCHAR(20) NOT NULL UNIQUE,
    referencia              VARCHAR(10) NOT NULL,
    complemento             VARCHAR(50),
    conta_contrato          VARCHAR(20),
    cliente_nome            VARCHAR(200),
    cliente_cnpj            VARCHAR(20),
    parceiro_negocio        VARCHAR(20),
    emissao                 DATE,
    apresentacao            DATE,
    vencimento              DATE,
    valor_total             DECIMAL(15,2),
    qtd_faturas_esperada    INTEGER,

    -- Energia/Tributos consolidados
    consumo_qtd             DECIMAL(15,2),
    consumo_valor           DECIMAL(15,2),
    consumo_ponta_qtd       DECIMAL(15,2),
    consumo_ponta_valor     DECIMAL(15,2),
    consumo_fp_qtd          DECIMAL(15,2),
    consumo_fp_valor        DECIMAL(15,2),
    demanda_ativa_qtd       DECIMAL(15,2),
    demanda_ativa_valor     DECIMAL(15,2),
    demanda_ultra_qtd       DECIMAL(15,2),
    demanda_ultra_valor     DECIMAL(15,2),
    consumo_reat_exc_qtd    DECIMAL(15,2),
    consumo_reat_exc_valor  DECIMAL(15,2),
    consumo_reat_exc_np_qtd    DECIMAL(15,2),
    consumo_reat_exc_np_valor  DECIMAL(15,2),
    consumo_reat_exc_fp_qtd    DECIMAL(15,2),
    consumo_reat_exc_fp_valor  DECIMAL(15,2),
    adicional_bandeira      DECIMAL(15,2),
    icms_total              DECIMAL(15,2),
    cofins_total            DECIMAL(15,2),
    pis_total               DECIMAL(15,2),
    subtotal_1              DECIMAL(15,2),

    -- Lançamentos e Serviços
    trib_reter_irpj         DECIMAL(15,2),
    trib_reter_pis          DECIMAL(15,2),
    trib_reter_cofins       DECIMAL(15,2),
    trib_reter_csll         DECIMAL(15,2),
    credito_dic_fic_dmic    DECIMAL(15,2),
    cip_ilum_pub            DECIMAL(15,2),
    subtotal_2              DECIMAL(15,2),

    -- Demonstrativo Valores Faturamento
    demo_energia            DECIMAL(15,2),
    demo_transmissao        DECIMAL(15,2),
    demo_distribuicao       DECIMAL(15,2),
    demo_enc_setoriais      DECIMAL(15,2),
    demo_tributos           DECIMAL(15,2),
    demo_soma               DECIMAL(15,2),

    -- Composição ICMS
    icms_base_calculo       DECIMAL(15,2),
    icms_aliquota           DECIMAL(8,4),
    icms_valor              DECIMAL(15,2),

    -- Controle de importação
    status                  VARCHAR(20) NOT NULL DEFAULT 'pendente',
    faturas_importadas      INTEGER DEFAULT 0,
    faturas_com_erro        INTEGER DEFAULT 0,
    arquivo_origem          VARCHAR(500),
    importado_em            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    erros_log               TEXT
);

CREATE INDEX IF NOT EXISTS idx_agrup_referencia ON fatura_agrupadora(referencia);
CREATE INDEX IF NOT EXISTS idx_agrup_complemento ON fatura_agrupadora(complemento);
CREATE INDEX IF NOT EXISTS idx_agrup_vencimento ON fatura_agrupadora USING BRIN(vencimento);
CREATE INDEX IF NOT EXISTS idx_agrup_status ON fatura_agrupadora(status);
CREATE INDEX IF NOT EXISTS idx_agrup_importado ON fatura_agrupadora USING BRIN(importado_em);

-- FK de arquivo_processado para fatura_agrupadora
ALTER TABLE arquivo_processado
    ADD CONSTRAINT fk_arq_agrupadora
    FOREIGN KEY (agrupadora_id) REFERENCES fatura_agrupadora(id)
    ON DELETE SET NULL;


-- =============================================
-- TABELA: Fatura individual (1 por instalação)
-- =============================================
CREATE TABLE IF NOT EXISTS fatura_individual (
    id                      SERIAL PRIMARY KEY,
    agrupadora_id           INTEGER NOT NULL REFERENCES fatura_agrupadora(id)
                            ON DELETE CASCADE,
    nota_fiscal             VARCHAR(30) NOT NULL,
    fatura_numero           VARCHAR(30),
    instalacao              VARCHAR(20) NOT NULL,
    nome_unidade            VARCHAR(200),
    endereco                VARCHAR(300),
    bairro                  VARCHAR(100),
    municipio               VARCHAR(100),
    unidade_leitura         VARCHAR(20),
    conj_contrato           VARCHAR(20),
    classe_principal        VARCHAR(10),
    classe_consumo          VARCHAR(20),
    tensao                  VARCHAR(5),
    fase                    DECIMAL(4,2),
    data_faturamento        DATE,
    dias_faturamento        INTEGER,
    data_leitura_anterior   DATE,
    data_leitura_atual      DATE,
    hash_code               VARCHAR(100),
    data_apresentacao       DATE,
    data_vencimento         DATE,
    data_recolhimento       DATE,
    valor                   DECIMAL(15,2),
    importado_em            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(nota_fiscal)
);

CREATE INDEX IF NOT EXISTS idx_fat_agrupadora ON fatura_individual(agrupadora_id);
CREATE INDEX IF NOT EXISTS idx_fat_instalacao ON fatura_individual(instalacao);
CREATE INDEX IF NOT EXISTS idx_fat_nome_unidade ON fatura_individual(nome_unidade);
CREATE INDEX IF NOT EXISTS idx_fat_tensao ON fatura_individual(tensao);
CREATE INDEX IF NOT EXISTS idx_fat_bairro ON fatura_individual(bairro);
CREATE INDEX IF NOT EXISTS idx_fat_data_fat ON fatura_individual USING BRIN(data_faturamento);
CREATE INDEX IF NOT EXISTS idx_fat_nota ON fatura_individual(nota_fiscal);


-- =============================================
-- TABELA: Tributos por fatura individual
-- =============================================
CREATE TABLE IF NOT EXISTS tributo (
    id                      SERIAL PRIMARY KEY,
    fatura_individual_id    INTEGER NOT NULL REFERENCES fatura_individual(id)
                            ON DELETE CASCADE,
    tipo                    VARCHAR(20) NOT NULL,
    base_calculo            DECIMAL(15,2),
    aliquota                DECIMAL(8,4),
    valor                   DECIMAL(15,2)
);

CREATE INDEX IF NOT EXISTS idx_tributo_fatura ON tributo(fatura_individual_id);


-- =============================================
-- TABELA: Valores faturados por fatura individual
-- =============================================
CREATE TABLE IF NOT EXISTS valor_faturado (
    id                      SERIAL PRIMARY KEY,
    fatura_individual_id    INTEGER NOT NULL REFERENCES fatura_individual(id)
                            ON DELETE CASCADE,
    descricao               VARCHAR(100) NOT NULL,
    quantidade              DECIMAL(15,2),
    preco                   DECIMAL(15,6),
    valor                   DECIMAL(15,2)
);

CREATE INDEX IF NOT EXISTS idx_valfat_fatura ON valor_faturado(fatura_individual_id);
CREATE INDEX IF NOT EXISTS idx_valfat_descricao ON valor_faturado(descricao);


-- =============================================
-- TABELA: Valores medidos (leituras)
-- =============================================
CREATE TABLE IF NOT EXISTS valor_medido (
    id                      SERIAL PRIMARY KEY,
    fatura_individual_id    INTEGER NOT NULL REFERENCES fatura_individual(id)
                            ON DELETE CASCADE,
    especie                 VARCHAR(10) NOT NULL,
    medidor                 VARCHAR(30),
    constante               DECIMAL(10,2),
    perc_fp                 DECIMAL(6,2),
    leitura_anterior        DECIMAL(15,2),
    leitura_atual           DECIMAL(15,2),
    medido                  DECIMAL(15,2),
    faturado                DECIMAL(15,2)
);

CREATE INDEX IF NOT EXISTS idx_valmed_fatura ON valor_medido(fatura_individual_id);


-- =============================================
-- TABELA: Log de importações
-- =============================================
CREATE TABLE IF NOT EXISTS log_importacao (
    id              SERIAL PRIMARY KEY,
    arquivo         VARCHAR(500) NOT NULL,
    inicio          TIMESTAMP NOT NULL,
    fim             TIMESTAMP,
    status          VARCHAR(20),
    total_arquivos  INTEGER,
    importados      INTEGER,
    duplicados      INTEGER,
    com_erro        INTEGER,
    mensagem        TEXT,
    detalhes        JSONB
);


-- =============================================
-- TABELA: Resultado de validações
-- =============================================
CREATE TABLE IF NOT EXISTS validacao_resultado (
    id                      SERIAL PRIMARY KEY,
    agrupadora_id           INTEGER REFERENCES fatura_agrupadora(id) ON DELETE CASCADE,
    fatura_individual_id    INTEGER REFERENCES fatura_individual(id) ON DELETE CASCADE,
    camada                  INTEGER NOT NULL,
    tipo                    VARCHAR(50) NOT NULL,
    resultado               VARCHAR(10) NOT NULL,
    valor_esperado          DECIMAL(15,2),
    valor_encontrado        DECIMAL(15,2),
    diferenca               DECIMAL(15,2),
    mensagem                TEXT,
    validado_em             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_valid_agrup ON validacao_resultado(agrupadora_id);
CREATE INDEX IF NOT EXISTS idx_valid_resultado ON validacao_resultado(resultado);


-- =============================================================
-- VIEWS PARA POWER BI
-- =============================================================

-- =============================================
-- VIEW PRINCIPAL: Fato consumo por unidade
-- =============================================
CREATE OR REPLACE VIEW vw_fato_consumo AS
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
    EXTRACT(YEAR FROM fa.vencimento)::INTEGER   AS ano,
    EXTRACT(MONTH FROM fa.vencimento)::INTEGER  AS mes,
    TO_CHAR(fa.vencimento, 'YYYY-MM')           AS ano_mes,

    -- Localização
    fi.nome_unidade,
    fi.endereco,
    fi.bairro,
    fi.municipio,

    -- Técnica
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

    -- Retenções
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
LEFT JOIN tributo t_pis              ON t_pis.fatura_individual_id = fi.id       AND t_pis.tipo = 'PIS';


-- =============================================
-- VIEW: Resumo mensal por grupo SEMED
-- =============================================
CREATE OR REPLACE VIEW vw_resumo_mensal AS
SELECT
    fa.referencia,
    fa.complemento                  AS grupo_semed,
    fa.vencimento,
    EXTRACT(YEAR FROM fa.vencimento)::INTEGER AS ano,
    EXTRACT(MONTH FROM fa.vencimento)::INTEGER AS mes,
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
FROM fatura_agrupadora fa;


-- =============================================
-- VIEW: Ranking de consumo por unidade
-- =============================================
CREATE OR REPLACE VIEW vw_ranking_unidades AS
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
LEFT JOIN valor_faturado ultra   ON ultra.fatura_individual_id = fi.id   AND ultra.descricao = 'Demanda Ultrapassagem';


-- =============================================
-- VIEW: Leituras dos medidores
-- =============================================
CREATE OR REPLACE VIEW vw_leituras AS
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
JOIN fatura_agrupadora fa ON fi.agrupadora_id = fa.id;


-- =============================================
-- VIEW: Tributos detalhados
-- =============================================
CREATE OR REPLACE VIEW vw_tributos_detalhado AS
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
JOIN fatura_agrupadora fa ON fi.agrupadora_id = fa.id;


-- =============================================
-- VIEW: Controle de importações
-- =============================================
CREATE OR REPLACE VIEW vw_controle_importacao AS
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
ORDER BY fa.importado_em DESC;


-- =============================================
-- DIMENSÃO: Calendário brasileiro
-- =============================================
CREATE OR REPLACE VIEW vw_dim_calendario AS
SELECT
    d::DATE                                     AS data,
    EXTRACT(YEAR FROM d)::INTEGER               AS ano,
    EXTRACT(MONTH FROM d)::INTEGER              AS mes,
    EXTRACT(DAY FROM d)::INTEGER                AS dia,
    TO_CHAR(d, 'YYYY-MM')                       AS ano_mes,
    TO_CHAR(d, 'TMMonth')                       AS nome_mes,
    TO_CHAR(d, 'TMDY')                          AS dia_semana,
    EXTRACT(QUARTER FROM d)::INTEGER            AS trimestre,
    'T' || EXTRACT(QUARTER FROM d)::TEXT        AS trimestre_label,
    EXTRACT(WEEK FROM d)::INTEGER               AS semana_ano,
    CASE WHEN EXTRACT(MONTH FROM d) <= 6 THEN 1 ELSE 2
    END                                         AS semestre,
    CASE WHEN EXTRACT(MONTH FROM d) BETWEEN 5 AND 11 THEN TRUE ELSE FALSE
    END                                         AS estacao_seca,
    CASE WHEN EXTRACT(MONTH FROM d) IN (12, 1, 2, 3, 4) THEN TRUE ELSE FALSE
    END                                         AS estacao_chuvosa,
    CASE WHEN EXTRACT(MONTH FROM d) BETWEEN 5 AND 11
         THEN 'Seca (Mai-Nov)'
         ELSE 'Chuvosa (Dez-Abr)'
    END                                         AS periodo_hidrologico
FROM generate_series('2020-01-01'::DATE, '2030-12-31'::DATE, '1 day') AS d;


COMMIT;
