-- =============================================================
-- SEMED Energia — Migration 002: Campos temporais
-- =============================================================
-- NOTA: a partir da versão SQLite, o esquema é criado pelos modelos
-- ORM em db/connection.py:init_db() (as colunas ano, mes e
-- complemento_norm já estão em faturas_agrupadoras). Este arquivo é
-- mantido apenas para referência/instalações legadas.
--
-- Em SQLite, ADD COLUMN falha se a coluna já existe; rode apenas em
-- bancos antigos que ainda não tenham estas colunas.
-- =============================================================

ALTER TABLE faturas_agrupadoras ADD COLUMN ano INTEGER;
ALTER TABLE faturas_agrupadoras ADD COLUMN mes INTEGER;
ALTER TABLE faturas_agrupadoras ADD COLUMN complemento_norm VARCHAR(20);

CREATE INDEX IF NOT EXISTS idx_fat_agr_ano_mes ON faturas_agrupadoras(ano, mes);
CREATE INDEX IF NOT EXISTS idx_fat_agr_complemento ON faturas_agrupadoras(complemento_norm);
