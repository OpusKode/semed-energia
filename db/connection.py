"""
Gerencia a conexao com o banco via SQLAlchemy.

Padrao: SQLite local (arquivo unico em DATA_DIR), sem servidor.
A URL pode ser sobrescrita por SEMED_DB_URL (ex.: PostgreSQL em dev).
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session

from config import DB_URL, garantir_pastas


_IS_SQLITE = DB_URL.startswith("sqlite")

# check_same_thread=False: a UI (PySide6) acessa o banco a partir de
# QThreads (workers). Como o acesso e serializado pelo app, e seguro.
_connect_args = {"check_same_thread": False} if _IS_SQLITE else {}

engine = create_engine(
    DB_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, connection_record):
        """Ativa integridade referencial e modo WAL a cada conexao."""
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Session:
    """Retorna uma nova sessao do banco."""
    return SessionLocal()


def testar_conexao() -> bool:
    """Testa se a conexao com o banco esta funcionando."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        raise ConnectionError(f"Falha ao conectar ao banco: {e}")


def init_db() -> None:
    """
    Inicializa o banco de forma idempotente:
      1. Garante as pastas de dados.
      2. Cria todas as tabelas a partir dos modelos ORM.
      3. (Re)cria as 7 views analiticas (Power BI) — somente no SQLite.

    As views (vw_fato_consumo, vw_resumo_mensal, etc.) sao consumidas por
    export/powerbi.py. No SQLite elas vem de db/views_sqlite.py; quando a URL
    aponta para PostgreSQL (override de dev via SEMED_DB_URL), as views ainda
    vivem nas migrations (db/migrations/001_initial.sql) e nao sao recriadas
    aqui (a sintaxe strftime/CTE e especifica do SQLite).

    Seguro para rodar a cada inicializacao do app.
    """
    garantir_pastas()
    from db.models import Base  # import tardio evita ciclo
    Base.metadata.create_all(engine)
    if _IS_SQLITE:
        from db.views_sqlite import criar_views_sqlite
        criar_views_sqlite(engine)


def executar_sql_file(caminho: str):
    """Executa um arquivo .sql inteiro contra o banco."""
    with open(caminho, "r", encoding="utf-8") as f:
        sql = f.read()
    with engine.begin() as conn:
        conn.execute(text(sql))
