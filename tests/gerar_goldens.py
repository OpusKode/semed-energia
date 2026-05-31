"""
Gera os goldens a partir das fixtures em modo standalone.

Use quando `pytest --update-golden` não rodar (ex.: ambientes com
tempfile.cleanup problemático, sandboxes restritivos). O efeito é o
mesmo: cria/atualiza tests/golden/<fixture>.json.

Uso:
    python tests/gerar_goldens.py             # regenera todos
    python tests/gerar_goldens.py 2026_referencia 2023_unico
"""
import json
import sys
from pathlib import Path

# sys.path setup (idêntico ao conftest)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_smoke import coletar_fixture, FIXTURES_DIR, GOLDEN_DIR


def main(argv):
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    if argv:
        nomes = argv
    else:
        nomes = sorted(d.name for d in FIXTURES_DIR.iterdir() if d.is_dir())

    for nome in nomes:
        dir_fixture = FIXTURES_DIR / nome
        if not dir_fixture.is_dir():
            print(f"[skip] {nome}: pasta não existe")
            continue

        print(f"[gerar] {nome} ... ", end="", flush=True)
        try:
            resultado = coletar_fixture(dir_fixture)
        except Exception as e:
            print(f"FALHA: {type(e).__name__}: {e}")
            continue

        golden = GOLDEN_DIR / f"{nome}.json"
        golden.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # Resumo no terminal
        n_pdfs = resultado["n_pdfs"]
        n_faturas = sum(
            (p.get("faturas") or {}).get("extraidas", 0) for p in resultado["pdfs"]
        )
        n_excs = sum(
            1 for p in resultado["pdfs"]
            if any(k.startswith("excecao") for k in p.get("classifier", {}))
            or any(k.startswith("excecao") for k in p.get("capa", {}))
        )
        print(f"ok ({n_pdfs} pdfs, {n_faturas} faturas, {n_excs} exceções)")


if __name__ == "__main__":
    main(sys.argv[1:])
