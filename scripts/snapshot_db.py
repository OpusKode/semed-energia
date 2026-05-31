"""
Exporta o estado atual do banco (agrupadoras + metadados) para JSON.

Uso:
    python scripts/snapshot_db.py
    python scripts/snapshot_db.py --saida snapshots/snap_antes.json

Gera snapshots/snap_AAAA-MM-DD_HHMMSS.json por padrão.
Não exporta faturas individuais completas — só metadados da agrupadora.
"""
import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# Adicionar raiz ao path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Tipo não serializável: {type(obj)}")


def tirar_snapshot(saida: Path | None = None) -> Path:
    """
    Consulta o banco e exporta metadados de agrupadoras para JSON.
    Retorna o caminho do arquivo gerado.
    """
    from db.connection import get_session, testar_conexao
    from sqlalchemy import text

    testar_conexao()
    session = get_session()

    try:
        rows = session.execute(text("""
            SELECT
                documento,
                referencia,
                complemento_norm,
                ano,
                mes,
                valor_total,
                faturas_importadas,
                faturas_com_erro,
                status,
                versao_layout,
                arquivo_origem
            FROM fatura_agrupadora
            ORDER BY ano NULLS LAST, mes NULLS LAST, complemento_norm NULLS LAST
        """)).fetchall()

        total_faturas_row = session.execute(
            text("SELECT COUNT(*) FROM fatura_individual")
        ).fetchone()
        total_faturas = int(total_faturas_row[0]) if total_faturas_row else 0

    finally:
        session.close()

    agrupadoras = []
    for r in rows:
        ag = {
            "documento":          r[0],
            "referencia":         r[1],
            "complemento_norm":   r[2],
            "ano":                r[3],
            "mes":                r[4],
            "valor_total":        float(r[5]) if r[5] is not None else None,
            "faturas_importadas": r[6],
            "faturas_com_erro":   r[7],
            "status":             r[8],
            "versao_layout":      r[9],
            "arquivo_origem":     r[10],
        }
        agrupadoras.append(ag)

    snapshot = {
        "gerado_em":         datetime.now().isoformat(timespec="seconds"),
        "total_agrupadoras": len(agrupadoras),
        "total_faturas":     total_faturas,
        "agrupadoras":       agrupadoras,
    }

    # Determinar destino
    pasta_snap = _ROOT / "snapshots"
    pasta_snap.mkdir(exist_ok=True)

    if saida is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        saida = pasta_snap / f"snap_{ts}.json"

    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    with open(saida, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=_decimal_default)

    return saida


def main():
    ap = argparse.ArgumentParser(
        description="Exporta metadados do banco para JSON (snapshot pré/pós reimport)."
    )
    ap.add_argument(
        "--saida", default=None,
        help="Caminho de saída (default: snapshots/snap_AAAA-MM-DD_HHMMSS.json)"
    )
    args = ap.parse_args()

    saida = tirar_snapshot(args.saida)
    print(f"Snapshot salvo em: {saida}")

    # Breve resumo
    with open(saida, encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Agrupadoras : {data['total_agrupadoras']}")
    print(f"  Faturas     : {data['total_faturas']}")
    print(f"  Gerado em   : {data['gerado_em']}")


if __name__ == "__main__":
    main()
