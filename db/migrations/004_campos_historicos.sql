-- =============================================
-- SEMED Energia — Migração 004
-- Adiciona colunas para campos históricos (layouts 2020-2024)
-- Data: 2026-05-15
-- =============================================
--
-- Contexto: a Fase 2 do plano de melhorias estende o parser para entender
-- os layouts antigos das faturas Equatorial (2020-2021: encargos por atraso
-- e bandeiras separadas; 2022+: devolução ICMS LC 194/2022; 2024+: diferença
-- de bandeira). Essas colunas armazenam os novos campos sem destruir dados
-- existentes.
--
-- Todas as colunas são nullable com default NULL:
--   - Faturas de layout moderno (2026) simplesmente ficam com NULL.
--   - Não há backfill necessário — os dados só existem em faturas antigas
--     que ainda precisam ser reimportadas (Fase 5).
--
-- Idempotente: `ADD COLUMN IF NOT EXISTS` — pode ser rodada mais de uma vez
-- sem erro e sem duplicar colunas.
-- =============================================

BEGIN;

ALTER TABLE fatura_agrupadora
    -- Layout 2020/2021: bandeira tarifária separada por cor
    ADD COLUMN IF NOT EXISTS bandeira_amarela      NUMERIC(15, 2),
    ADD COLUMN IF NOT EXISTS bandeira_vermelha     NUMERIC(15, 2),
    -- Layout 2020/2021: encargos por atraso de pagamento
    ADD COLUMN IF NOT EXISTS correcao_monetaria    NUMERIC(15, 2),
    ADD COLUMN IF NOT EXISTS multa                 NUMERIC(15, 2),
    ADD COLUMN IF NOT EXISTS juros                 NUMERIC(15, 2),
    -- Layout 2022+: crédito de devolução ICMS LC 194/2022
    ADD COLUMN IF NOT EXISTS devolucao_icms_lc194  NUMERIC(15, 2),
    -- Layout 2024+: diferença de bandeira tarifária
    ADD COLUMN IF NOT EXISTS diferenca_bandeira    NUMERIC(15, 2),
    -- Versão de layout detectada pelo parser ("v2020", "v2022", "v2026")
    ADD COLUMN IF NOT EXISTS versao_layout         VARCHAR(10);

COMMIT;
