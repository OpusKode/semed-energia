-- =============================================
-- SEMED Energia — Migração 005
-- Adiciona hierarquia temporal à fatura_agrupadora
-- Data: 2026-05-15
-- =============================================
--
-- Contexto: a Fase 3 do plano de melhorias adiciona identidade temporal
-- inequívoca a cada agrupadora. Hoje `complemento` ("SEMED-I") repete em
-- todos os meses/anos — a UI não consegue distinguir SEMED-I jan/2020 de
-- SEMED-I dez/2026 sem olhar a coluna `referencia` (string "MM/AAAA").
--
-- Esta migração:
--   1) Adiciona `ano` e `mes` (inteiros indexados) — derivados de `referencia`.
--   2) Adiciona `complemento_norm` (forma canônica "SEMED-I"..."SEMED-IV") —
--      derivado de `complemento` (que pode aparecer como "SEMED I", "SEMED 4",
--      "SEMED-III", etc.).
--   3) Cria índices compostos para queries de série temporal.
--   4) Cria UNIQUE(ano, mes, complemento_norm) para integridade conceitual.
--      NOTA: PostgreSQL permite múltiplos NULLs em colunas com UNIQUE — registros
--      sem referência/complemento parseáveis não violam o constraint.
--
-- Idempotente: todos os DDLs usam IF NOT EXISTS; o UNIQUE é criado via bloco
-- DO $$ que verifica pg_constraint antes de adicionar.
-- =============================================

BEGIN;

ALTER TABLE fatura_agrupadora
    ADD COLUMN IF NOT EXISTS ano              SMALLINT,
    ADD COLUMN IF NOT EXISTS mes             SMALLINT,
    ADD COLUMN IF NOT EXISTS complemento_norm VARCHAR(20);

CREATE INDEX IF NOT EXISTS ix_ag_ano_mes
    ON fatura_agrupadora(ano, mes);

CREATE INDEX IF NOT EXISTS ix_ag_complemento_norm
    ON fatura_agrupadora(complemento_norm);

-- Unique constraint em bloco DO para poder checar existência antes de criar.
-- Não usa CREATE UNIQUE INDEX IF NOT EXISTS para manter consistência com
-- o catálogo de constraints (pg_constraint) e facilitar inspeção via psql \d.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ux_ag_ano_mes_comp'
    ) THEN
        ALTER TABLE fatura_agrupadora
            ADD CONSTRAINT ux_ag_ano_mes_comp
            UNIQUE (ano, mes, complemento_norm);
    END IF;
END $$;

COMMIT;
