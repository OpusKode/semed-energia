-- =============================================
-- SEMED Energia — Migração 002
-- Índices explícitos para as colunas de dedup
-- Data: 2026-04-15
-- =============================================
--
-- Contexto: o achado de review apontava table scans em `arquivo_processado.hash_sha256`,
-- `fatura_agrupadora.documento` e `fatura_individual.nota_fiscal` durante a dedup
-- (C1/C2/C3). Em PostgreSQL, restrições UNIQUE já geram um índice btree implícito,
-- então na prática essas colunas NÃO fazem seq scan — a UNIQUE constraint em
-- `arquivo_processado.hash_sha256`, `fatura_agrupadora.documento` e
-- `fatura_individual.nota_fiscal` (001_initial.sql) cobre isso.
--
-- Esta migração existe por dois motivos:
--   1) Documentar explicitamente que dedup depende destes índices (se alguém
--      um dia remover uma UNIQUE, a cobertura de índice fica explicita aqui).
--   2) Garantir o índice extra em `fatura_agrupadora.documento`, que hoje só
--      tem o índice implícito da UNIQUE — deixamos um nome estável para
--      monitoramento/EXPLAIN.
--
-- Todos os CREATE INDEX usam IF NOT EXISTS, portanto são idempotentes.
-- =============================================

BEGIN;

-- Dedup C1: hash SHA-256 do arquivo
CREATE INDEX IF NOT EXISTS idx_arq_hash_sha256
    ON arquivo_processado(hash_sha256);

-- Dedup C2: documento da agrupadora
CREATE INDEX IF NOT EXISTS idx_agrup_documento
    ON fatura_agrupadora(documento);

-- Dedup C3: nota fiscal individual
CREATE INDEX IF NOT EXISTS idx_fat_nota_fiscal
    ON fatura_individual(nota_fiscal);

COMMIT;
