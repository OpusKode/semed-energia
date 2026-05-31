"""
SEMED Energia — Runner de migrações incrementais (LEGADO / somente PostgreSQL).

>>> No caminho SQLite (padrão de produção) este script é um NO-OP: o esquema
    completo é criado por db.connection.init_db() (tabelas via ORM + views via
    db/views_sqlite.py). As migrations 001–005 abaixo são DDL específico de
    PostgreSQL e só fazem sentido quando SEMED_DB_URL aponta para um Postgres
    de desenvolvimento. <<<

Aplica as migrations 001–005 em ordem, pulando as que já foram aplicadas.
Todas as migrations são idempotentes (ADD COLUMN IF NOT EXISTS, CREATE INDEX
IF NOT EXISTS, DO $$ com checagem em pg_constraint).

Uso (apenas PostgreSQL):
    python scripts/migrate.py            # aplica todas as pendentes
    python scripts/migrate.py --check    # só lista o estado, não aplica nada
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.connection import engine, testar_conexao
from sqlalchemy import text

MIGRATIONS_DIR = ROOT / "db" / "migrations"

# Ordem determinística das migrations.
MIGRATIONS = [
    "001_initial.sql",
    "002_dedup_indexes.sql",
    "003_consumo_kwh.sql",
    "004_campos_historicos.sql",
    "005_indexacao_temporal.sql",
]

# Colunas/índices que revelam se cada migration foi aplicada.
# Serve como "canary" rápido para o modo --check.
_CANARIOS = {
    "001_initial.sql":         ("tabela",  "fatura_agrupadora"),
    "002_dedup_indexes.sql":   ("indice",  "ix_fa_documento"),
    "003_consumo_kwh.sql":     ("coluna",  "fatura_individual", "consumo_kwh"),
    "004_campos_historicos.sql": ("coluna", "fatura_agrupadora", "versao_layout"),
    "005_indexacao_temporal.sql": ("coluna", "fatura_agrupadora", "complemento_norm"),
}


def _aplicada(conn, migration: str) -> bool:
    """Heurística rápida: verifica se o artefato principal da migration existe."""
    canario = _CANARIOS.get(migration)
    if canario is None:
        return False

    if canario[0] == "tabela":
        r = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :nome
        """), {"nome": canario[1]})
        return r.fetchone() is not None

    if canario[0] == "coluna":
        _, tabela, coluna = canario
        r = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name  = :tab
              AND column_name = :col
        """), {"tab": tabela, "col": coluna})
        return r.fetchone() is not None

    if canario[0] == "indice":
        r = conn.execute(text("""
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = :nome
        """), {"nome": canario[1]})
        return r.fetchone() is not None

    return False


def _executar_migration(conn, caminho: Path):
    """Executa um arquivo .sql inteiro, ignorando comentários em bloco."""
    sql = caminho.read_text(encoding="utf-8")
    conn.execute(text(sql))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Runner de migrações SEMED Energia")
    parser.add_argument(
        "--check", action="store_true",
        help="Apenas verifica quais migrations estão pendentes, sem aplicar."
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  SEMED Energia — Migrações do banco")
    print("=" * 60)

    # Caminho SQLite: migrations legadas não se aplicam. O esquema vem de
    # init_db() (tabelas via ORM + views via db/views_sqlite.py).
    if engine.dialect.name == "sqlite":
        print("\nℹ  Banco SQLite detectado — migrations legadas não se aplicam.")
        print("   O esquema é criado/atualizado por db.connection.init_db().")
        print("   Garantindo esquema agora…")
        from db.connection import init_db
        init_db()
        print("   ✓ Esquema SQLite pronto (tabelas + views).")
        return

    # Testar conexão
    print("\n🔌 Verificando conexão com o banco…")
    try:
        testar_conexao()
        print("   ✓ Conexão OK")
    except Exception as e:
        print(f"   ✗ Falha: {e}")
        sys.exit(1)

    pendentes = []
    aplicadas = []

    with engine.connect() as conn:
        for nome in MIGRATIONS:
            caminho = MIGRATIONS_DIR / nome
            if not caminho.exists():
                print(f"\n   ⚠  Arquivo não encontrado: {caminho}")
                continue
            ja_aplicada = _aplicada(conn, nome)
            if ja_aplicada:
                aplicadas.append(nome)
            else:
                pendentes.append((nome, caminho))

    print(f"\n📋 Estado das migrations ({len(MIGRATIONS)} no total):")
    for nome in aplicadas:
        print(f"   ✓ {nome}")
    for nome, _ in pendentes:
        print(f"   ○ {nome}  ← PENDENTE")

    if not pendentes:
        print("\n✅ Banco já está atualizado. Nenhuma migration pendente.")
        return

    if args.check:
        print(f"\n⚠  {len(pendentes)} migration(s) pendente(s). "
              "Rode sem --check para aplicar.")
        sys.exit(1)

    print(f"\n🚀 Aplicando {len(pendentes)} migration(s)…")
    with engine.connect() as conn:
        for nome, caminho in pendentes:
            print(f"   → {nome}… ", end="", flush=True)
            try:
                _executar_migration(conn, caminho)
                print("✓")
            except Exception as e:
                print(f"✗\n\n   ERRO: {e}")
                print("\n❌ Migration interrompida. Corrija o erro e tente novamente.")
                sys.exit(1)

    print("\n✅ Todas as migrations aplicadas com sucesso!")
    print("\n   Próximo passo:")
    print("   python scripts/snapshot_db.py")


if __name__ == "__main__":
    main()
