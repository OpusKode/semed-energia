-- =============================================
-- SEMED Energia — Backfill temporal
-- Preenche ano, mes e complemento_norm em fatura_agrupadora
-- para registros importados antes da Fase 3.
-- =============================================
--
-- Pré-requisito: migration 005_indexacao_temporal.sql já aplicada.
-- Idempotente: cada UPDATE filtra apenas linhas que ainda não têm o campo.
--
-- Execute com: psql -d <banco> -f scripts/backfill_temporal.sql
-- =============================================

BEGIN;

-- ── 1. Preencher mes e ano a partir de referencia ("MM/AAAA") ──────────────
--
-- SPLIT_PART(referencia, '/', 1) → "MM"
-- SPLIT_PART(referencia, '/', 2) → "AAAA"
-- ::SMALLINT faz o cast; se o valor não for numérico a query falha com erro
-- explícito (melhor que silêncio). Linhas com referencia NULL são ignoradas
-- pelo filtro WHERE.

UPDATE fatura_agrupadora
SET
    mes = SPLIT_PART(referencia, '/', 1)::SMALLINT,
    ano = SPLIT_PART(referencia, '/', 2)::SMALLINT
WHERE referencia IS NOT NULL
  AND referencia LIKE '%/%'
  AND (mes IS NULL OR ano IS NULL);

-- ── 2. Preencher complemento_norm a partir de complemento ──────────────────
--
-- Lógica de normalização:
--   a) Extrai o sufixo após "SEMED" (com espaço, hífen, ou sem separador).
--   b) Converte numerais arábicos (1, 2, 3, 4) para romano (I, II, III, IV).
--   c) Formato canônico: "SEMED-" + romano.
--   d) Se o sufixo não for reconhecido: "SEMED-?".
--
-- Usa REGEXP_REPLACE para limpar o separador e UPPER/TRIM para normalizar.
-- Função nativa do PostgreSQL — sem extensões extras.
--
-- Mapeamento de variações reais observadas no sistema:
--   "SEMED I"    → "SEMED-I"
--   "SEMED-I"   → "SEMED-I"
--   "SEMED  I"  → "SEMED-I"    (múltiplos espaços)
--   "SEMED II"  → "SEMED-II"
--   "SEMED-II"  → "SEMED-II"
--   "SEMED III" → "SEMED-III"
--   "SEMED IV"  → "SEMED-IV"
--   "SEMED-IV"  → "SEMED-IV"
--   "SEMED 4"   → "SEMED-IV"
--   "SEMED4"    → "SEMED-IV"
--   qualquer outra coisa → "SEMED-?"

UPDATE fatura_agrupadora
SET complemento_norm =
    CASE
        -- Extrai sufixo: tudo após "SEMED" + separador opcional (espaço/hífen/nada)
        -- Trim + Upper para normalizar.
        WHEN UPPER(TRIM(
                REGEXP_REPLACE(complemento, '^SEMED[\s\-]*', '', 'i')
             )) IN ('I', '1')   THEN 'SEMED-I'
        WHEN UPPER(TRIM(
                REGEXP_REPLACE(complemento, '^SEMED[\s\-]*', '', 'i')
             )) IN ('II', '2')  THEN 'SEMED-II'
        WHEN UPPER(TRIM(
                REGEXP_REPLACE(complemento, '^SEMED[\s\-]*', '', 'i')
             )) IN ('III', '3') THEN 'SEMED-III'
        WHEN UPPER(TRIM(
                REGEXP_REPLACE(complemento, '^SEMED[\s\-]*', '', 'i')
             )) IN ('IV', '4')  THEN 'SEMED-IV'
        ELSE 'SEMED-?'
    END
WHERE complemento_norm IS NULL;

-- ── Verificação pós-backfill ────────────────────────────────────────────────
-- Execute este SELECT para confirmar que 0 linhas precisam de atenção:
--
--   SELECT COUNT(*) FROM fatura_agrupadora
--   WHERE referencia IS NOT NULL
--     AND (mes IS NULL OR ano IS NULL OR complemento_norm IS NULL);
--
-- Linhas com referencia NULL são esperadas em registros legados sem data —
-- elas ficam com ano/mes NULL (o constraint UNIQUE permite múltiplos NULLs).

COMMIT;
