"""
Smoke test por fixture.

Para cada subpasta em tests/fixtures/, roda classifier + capa_parser +
detalhe_parser em modo offline (sem DB, sem mover arquivos) e captura
um resumo determinístico em JSON. Esse JSON é comparado contra o
golden em tests/golden/<fixture>.json.

Uso:
    pytest tests/test_smoke.py                 # valida contra golden
    pytest tests/test_smoke.py --update-golden # reescreve goldens

Filosofia:
- O objetivo NÃO é validar que o sistema acerta — hoje ele erra na
  maioria das fixtures (esse é exatamente o bug que estamos corrigindo).
- O objetivo é congelar o estado ATUAL como baseline. Assim, ao
  implementar as Fases 1-2, qualquer mudança aparece num diff
  legível e é conscientemente "abençoada" via --update-golden.
- Capturamos resumos (contagens, primeiros campos), não dumps completos:
  goldens menores, diffs mais legíveis, menos ruído por mudanças
  cosméticas (espaços, ordenação de avisos, etc.).

Erros são capturados como strings "ExcecaoX: mensagem" em vez de
quebrarem o teste, pra que TODOS os fixtures sempre rodem até o fim.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


# =============================================================
# Coleta de fatos por PDF (offline, sem DB)
# =============================================================

def _safe(fn, *args, **kwargs):
    """Executa fn e retorna ou (valor, None) ou (None, "Tipo: msg")."""
    try:
        return fn(*args, **kwargs), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _stringify(v):
    """Converte Decimal/date/None pra string estável no JSON."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    # date/datetime
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def coletar_fatos_pdf(pdf_path: Path) -> dict:
    """
    Roda classifier + capa + detalhe num PDF e devolve um dict pequeno
    e determinístico para comparação com golden.
    """
    fatos = {
        "arquivo": pdf_path.name,
        "tamanho_bytes": pdf_path.stat().st_size,
    }

    # ----- abertura básica e varredura de "FATURA AGRUPADORA" -----
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        fatos["paginas_total"] = len(doc)
        all_text = "\n".join(doc[i].get_text() for i in range(min(len(doc), 200)))
        fatos["ocorrencias_FATURA_AGRUPADORA"] = all_text.count("FATURA AGRUPADORA")
        doc.close()
    except Exception as e:
        fatos["erro_abrir"] = f"{type(e).__name__}: {e}"
        return fatos

    # ----- classifier -----
    from parser.classifier import classificar_pdf

    cls, err = _safe(classificar_pdf, pdf_path)
    if err is not None:
        fatos["classifier"] = {"excecao": err}
    else:
        fatos["classifier"] = {
            "eh_equatorial": cls.eh_equatorial,
            "cnpj": cls.cnpj,
            "cnpj_valido": cls.cnpj_valido,
            "erro_interno": cls.erro,
            "n_paginas_capa": len(cls.paginas_capa),
            "n_paginas_b3": len(cls.paginas_b3),
            "n_paginas_a4": len(cls.paginas_a4),
            "tipos_por_pagina": [p.tipo for p in cls.paginas],
        }

    # ----- capa -----
    from parser.capa_parser import parsear_capa

    capa, err = _safe(parsear_capa, pdf_path)
    if err is not None:
        fatos["capa"] = {"excecao": err}
    else:
        fatos["capa"] = {
            "documento": capa.documento,
            "complemento": capa.complemento,
            "referencia": capa.referencia,
            "conta_contrato": capa.conta_contrato,
            "cliente_cnpj": capa.cliente_cnpj,
            "emissao": _stringify(capa.emissao),
            "vencimento": _stringify(capa.vencimento),
            "valor_total": _stringify(capa.valor_total),
            "qtd_faturas_esperada": capa.qtd_faturas_esperada,
            "campos_extraidos": capa.campos_extraidos,
            "campos_esperados": capa.campos_esperados,
            "n_avisos": len(capa.avisos),
            "primeiros_avisos": sorted(capa.avisos)[:5],
        }

    # ----- detalhe (B3/A4) -----
    fatos["faturas"] = _coletar_faturas(pdf_path)

    return fatos


def _coletar_faturas(pdf_path: Path) -> dict:
    """Roda os parsers de detalhe e devolve resumo."""
    try:
        import pdfplumber

        from parser.classifier import classificar_pdf
        from parser.detalhe_parser import parsear_pagina_b3, parsear_pagina_a4
    except Exception as e:
        return {"excecao_import": f"{type(e).__name__}: {e}"}

    try:
        cls = classificar_pdf(pdf_path)
    except Exception as e:
        return {"excecao_classifier": f"{type(e).__name__}: {e}"}

    faturas = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for p in cls.paginas:
            try:
                if p.tipo == "detalhe_b3":
                    faturas.extend(parsear_pagina_b3(pdf.pages[p.numero], p.numero))
                elif p.tipo == "detalhe_a4":
                    f = parsear_pagina_a4(pdf.pages[p.numero], p.numero)
                    if f is not None:
                        faturas.append(f)
            except Exception as e:
                # Não estoura — guarda como aviso pra aparecer no golden.
                faturas_excecao = f"pag={p.numero} {type(e).__name__}: {e}"
                # Anexa direto na lista pra o resumo capturar
                # (não é um DadosFaturaDetalhe, então tratamos abaixo)
                faturas.append({"_excecao": faturas_excecao})

    excecoes = [f for f in faturas if isinstance(f, dict)]
    faturas_validas = [f for f in faturas if not isinstance(f, dict)]

    return {
        "extraidas": len(faturas_validas),
        "com_nota_fiscal": sum(1 for f in faturas_validas if f.nota_fiscal),
        "com_instalacao": sum(1 for f in faturas_validas if f.instalacao),
        "tensoes_distintas": sorted({f.tensao for f in faturas_validas if f.tensao}),
        "primeiras_notas_fiscais": [
            f.nota_fiscal for f in faturas_validas if f.nota_fiscal
        ][:5],
        "amostra": [
            {
                "nota_fiscal": f.nota_fiscal,
                "instalacao": f.instalacao,
                "nome_unidade": f.nome_unidade,
                "tensao": f.tensao,
                "valor": _stringify(f.valor),
            }
            for f in faturas_validas[:3]
        ],
        "n_excecoes_pagina": len(excecoes),
    }


# =============================================================
# Coleta por fixture (varre todos os PDFs do diretório)
# =============================================================

def coletar_fixture(dir_fixture: Path) -> dict:
    # Inclui .pdf e .PDF. No Windows o glob é case-insensitive, então
    # deduplicamos por nome lowercase para não contar o mesmo arquivo duas vezes.
    # Se existirem dois arquivos com mesmo nome em cases distintos (raro),
    # o primeiro encontrado vence — o usuário pode renomear se quiser ambos.
    vistos: dict[str, Path] = {}
    for p in list(dir_fixture.glob("*.pdf")) + list(dir_fixture.glob("*.PDF")):
        vistos.setdefault(p.name.lower(), p)
    pdfs = sorted(vistos.values(), key=lambda p: p.name.lower())
    return {
        "fixture": dir_fixture.name,
        "n_pdfs": len(pdfs),
        "pdfs": [coletar_fatos_pdf(p) for p in pdfs],
    }


# =============================================================
# Test parametrizado
# =============================================================

def _fixtures_disponiveis():
    if not FIXTURES_DIR.exists():
        return []
    return sorted(
        d.name for d in FIXTURES_DIR.iterdir()
        if d.is_dir() and any(d.glob("*.pdf")) or any(d.glob("*.PDF"))
    )


@pytest.mark.parametrize("fixture", _fixtures_disponiveis())
def test_fixture_contra_golden(fixture, request):
    update = request.config.getoption("--update-golden")

    dir_fixture = FIXTURES_DIR / fixture
    resultado = coletar_fixture(dir_fixture)

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    golden_path = GOLDEN_DIR / f"{fixture}.json"

    if update:
        golden_path.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # Não falha — só registrou.
        return

    if not golden_path.exists():
        pytest.fail(
            f"Golden ausente: {golden_path.name}. "
            f"Rode 'pytest tests/test_smoke.py --update-golden' uma vez para gerá-lo."
        )

    esperado = json.loads(golden_path.read_text(encoding="utf-8"))

    if resultado == esperado:
        return

    # Diff legível: aponta a primeira diferença em vez de despejar dois JSONs gigantes.
    diff = _primeiro_diff(esperado, resultado, caminho=f"<{fixture}>")
    pytest.fail(
        f"Saída divergiu do golden em {golden_path.name}.\n"
        f"Primeira diferença: {diff}\n"
        f"Se a mudança é intencional, rode 'pytest --update-golden' para abençoar."
    )


def _primeiro_diff(a, b, caminho=""):
    """Retorna string descrevendo a primeira divergência entre dois objetos."""
    if type(a) is not type(b):
        return f"{caminho}: tipo {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        chaves_a = set(a)
        chaves_b = set(b)
        if chaves_a != chaves_b:
            faltam_em_b = chaves_a - chaves_b
            sobram_em_b = chaves_b - chaves_a
            return f"{caminho}: chaves faltando={sorted(faltam_em_b)} sobrando={sorted(sobram_em_b)}"
        for k in sorted(chaves_a):
            d = _primeiro_diff(a[k], b[k], caminho + f".{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{caminho}: comprimento {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _primeiro_diff(x, y, caminho + f"[{i}]")
            if d:
                return d
        return ""
    if a != b:
        return f"{caminho}: {a!r} vs {b!r}"
    return ""
