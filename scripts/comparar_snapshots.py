"""
Compara dois snapshots gerados por snapshot_db.py e imprime um diff legível.

Uso:
    python scripts/comparar_snapshots.py snapshots/snap_antes.json snapshots/snap_depois.json
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def _carregar(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _por_chave(agrupadoras: list[dict]) -> dict[str, dict]:
    """Indexa lista de agrupadoras por 'documento' (chave única)."""
    return {ag["documento"]: ag for ag in agrupadoras if ag.get("documento")}


def main():
    ap = argparse.ArgumentParser(
        description="Compara dois snapshots de banco (antes/depois do reimport)."
    )
    ap.add_argument("antes",  help="Caminho do snapshot anterior (JSON).")
    ap.add_argument("depois", help="Caminho do snapshot posterior (JSON).")
    args = ap.parse_args()

    try:
        ant = _carregar(args.antes)
        dep = _carregar(args.depois)
    except FileNotFoundError as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)

    n_antes  = ant["total_agrupadoras"]
    n_depois = dep["total_agrupadoras"]
    f_antes  = ant["total_faturas"]
    f_depois = dep["total_faturas"]

    delta_ag  = n_depois - n_antes
    delta_fat = f_depois - f_antes
    sinal_ag  = f"+{delta_ag}"  if delta_ag  >= 0 else str(delta_ag)
    sinal_fat = f"+{delta_fat}" if delta_fat >= 0 else str(delta_fat)

    print()
    print("Comparação de snapshots")
    print("=======================")
    print(f"Snapshot anterior : {args.antes}  ({ant['gerado_em']})")
    print(f"Snapshot posterior: {args.depois}  ({dep['gerado_em']})")
    print()
    print(f"Agrupadoras: {n_antes:>5} → {n_depois:<5}  ({sinal_ag})")
    print(f"Faturas    : {f_antes:>5} → {f_depois:<5}  ({sinal_fat})")

    # ── Novas agrupadoras (estão depois mas não antes) ─────────────────────
    idx_ant = _por_chave(ant["agrupadoras"])
    idx_dep = _por_chave(dep["agrupadoras"])

    docs_novas   = set(idx_dep.keys()) - set(idx_ant.keys())
    docs_perdidas = set(idx_ant.keys()) - set(idx_dep.keys())

    print()
    print("Novas agrupadoras (por ano):")
    if docs_novas:
        por_ano: dict[int | None, list[str]] = defaultdict(list)
        for doc in docs_novas:
            ag = idx_dep[doc]
            por_ano[ag.get("ano")].append(ag.get("complemento_norm") or "?")

        for ano in sorted(k for k in por_ano if k is not None):
            comps = sorted(set(por_ano[ano]))
            print(f"  {ano}: {len(por_ano[ano])}  ({', '.join(comps)})")
        if None in por_ano:
            print(f"  (ano desconhecido): {len(por_ano[None])}")
    else:
        print("  (nenhuma)")

    print()
    print("Agrupadoras perdidas (estavam antes, não estão depois):")
    if docs_perdidas:
        for doc in sorted(docs_perdidas):
            ag = idx_ant[doc]
            print(f"  {doc}  {ag.get('complemento_norm')} {ag.get('referencia')}")
    else:
        print("  (nenhuma — esperado)")

    # ── Campos históricos agora preenchidos ───────────────────────────────
    campos_hist = [
        "bandeira_amarela", "multa", "juros", "correcao_monetaria",
        "bandeira_vermelha", "devolucao_icms_lc194", "diferenca_bandeira",
    ]
    docs_comuns = set(idx_ant.keys()) & set(idx_dep.keys())

    print()
    print("Campos históricos preenchidos nas agrupadoras comuns:")
    qualquer = False
    for campo in campos_hist:
        n_ant_preench = sum(
            1 for doc in docs_comuns
            if idx_ant[doc].get(campo) is not None
        )
        n_dep_preench = sum(
            1 for doc in docs_comuns
            if idx_dep[doc].get(campo) is not None
        )
        if n_dep_preench != n_ant_preench:
            delta = n_dep_preench - n_ant_preench
            sinal = f"+{delta}" if delta >= 0 else str(delta)
            print(f"  {campo:<28}: {n_ant_preench} → {n_dep_preench}  ({sinal})")
            qualquer = True
    if not qualquer:
        print("  (sem alterações nos campos históricos das agrupadoras comuns)")

    # ── Cobertura por ano/complemento_norm (novas) ─────────────────────────
    print()
    print("Cobertura das novas agrupadoras (ano × complemento_norm × qtd meses):")
    if docs_novas:
        grade: dict[tuple, int] = defaultdict(int)
        for doc in docs_novas:
            ag = idx_dep[doc]
            chave = (ag.get("ano"), ag.get("complemento_norm") or "?")
            grade[chave] += 1

        for (ano, comp), qtd in sorted(grade.items()):
            print(f"  {ano} | {comp:<12} | {qtd} mês(es)")
    else:
        print("  (nenhuma agrupadora nova)")

    print()


if __name__ == "__main__":
    main()
