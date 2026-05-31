"""
SEMED Energia — Setup / inicialização do banco (SQLite).

Uso:
    python setup.py

Ações (idempotentes):
    1. Cria as pastas do sistema (entrada/, processados/, etc.).
    2. Cria o arquivo SQLite e todas as tabelas/índices/views.
    3. Verifica se o esquema foi criado corretamente.

Não há pré-requisitos de servidor: o banco é um arquivo local.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import TODAS_AS_PASTAS, DATA_DIR, DB_PATH, garantir_pastas
from db.connection import init_db, testar_conexao, engine
from sqlalchemy import inspect


TABELAS_ESPERADAS = [
    "arquivo_processado",
    "fatura_agrupadora",
    "fatura_individual",
    "tributo",
    "valor_faturado",
    "valor_medido",
    "log_importacao",
    "validacao_resultado",
]


def main() -> int:
    print("\n" + "=" * 60)
    print("  SEMED Energia — Setup do banco (SQLite)")
    print("=" * 60)

    print("\nCriando pastas do sistema...")
    garantir_pastas()
    for p in TODAS_AS_PASTAS:
        print(f"   OK  {p}")

    print(f"\nInicializando banco em:\n   {DB_PATH}")
    init_db()
    testar_conexao()
    print("   OK  esquema criado/atualizado")

    print("\nVerificando tabelas...")
    tabelas = set(inspect(engine).get_table_names())
    faltando = [t for t in TABELAS_ESPERADAS if t not in tabelas]
    if faltando:
        print(f"   ERRO  tabelas ausentes: {faltando}")
        return 1
    for t in TABELAS_ESPERADAS:
        print(f"   OK  {t}")

    print("\nSetup concluído. Dados em:")
    print(f"   {DATA_DIR}")
    print("\nExecute a interface com:  python -m ui.app\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
