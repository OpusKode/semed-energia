-- =============================================
-- SEMED Energia — Migração 003
-- Persiste consumo_kwh na fatura_individual
-- Data: 2026-04-15
-- =============================================
--
-- Contexto: `_fatura_to_dict` em `db/repository.py` recalculava
-- `consumo_kwh = sum(valor_faturado where descricao like 'Consumo%')` a cada
-- carga da UI. Com 1k+ faturas isso vira custo O(N*M) — e como o valor e
-- imutavel pos-importacao, da pra persistir de uma vez.
--
-- Esta migracao:
--   1) Adiciona `consumo_kwh` em `fatura_individual`.
--   2) Faz BACKFILL a partir de `valor_faturado` para registros existentes.
--
-- Idempotente: `ADD COLUMN IF NOT EXISTS` + UPDATE so mexe em linhas com
-- `consumo_kwh IS NULL`, entao rodar novamente nao causa dano.
-- =============================================

BEGIN;

ALTER TABLE fatura_individual
    ADD COLUMN IF NOT EXISTS consumo_kwh DECIMAL(15, 2);

-- Backfill: soma dos valores_faturados com descricao começando com "Consumo".
UPDATE fatura_individual fi
SET consumo_kwh = sub.total
FROM (
    SELECT vf.fatura_individual_id AS fid,
           COALESCE(SUM(vf.quantidade), 0) AS total
    FROM valor_faturado vf
    WHERE vf.descricao LIKE 'Consumo%'
    GROUP BY vf.fatura_individual_id
) sub
WHERE fi.id = sub.fid
  AND fi.consumo_kwh IS NULL;

COMMIT;
