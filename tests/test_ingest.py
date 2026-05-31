"""
Testes do módulo de ingestão (Fase 1).

Diferente de `test_smoke.py`, estes testes NÃO comparam contra golden —
fazem asserts diretos sobre o comportamento esperado de cada função do
`ingest/`. Usam as mesmas fixtures de `tests/fixtures/`.

PDFs lógicos gerados pelo splitter/merger vão para `tmp_path` (pytest) e
são descartados automaticamente após cada teste.
"""
from pathlib import Path

import fitz
import pytest

from ingest.classifier_pasta import classificar_arquivos
from ingest.detector_formato import capas_reais_doc, detectar_formato
from ingest.merger import fundir_fragmentado
from ingest.orquestrador import expandir_pasta_historica
from ingest.scanner import scan_mes
from ingest.splitter import dividir_consolidado
from ingest.tipos import ArquivoIngest

# ─── Caminhos para FATURAS - SEMED real ──────────────────────
_RAIZ = Path(__file__).parent.parent / "FATURAS - SEMED"
_2020 = _RAIZ / "EQUATORIAL - FATURAS - 2020"
_2026 = _RAIZ / "EQUATORIAL - FATURA - 2026"

FIXTURES = Path(__file__).parent / "fixtures"


def _pdfs(subpasta: str) -> list[Path]:
    """PDFs de uma fixture, sem duplicar por case (.pdf vs .PDF)."""
    pasta = FIXTURES / subpasta
    vistos: dict[str, Path] = {}
    for p in pasta.iterdir():
        if p.is_file() and p.suffix.lower() == ".pdf":
            vistos.setdefault(p.name.lower(), p)
    return sorted(vistos.values(), key=lambda p: p.name.lower())


# =============================================================
# detector_formato
# =============================================================

def test_detector_formato_2026_unico():
    assert detectar_formato(_pdfs("2026_referencia")) == "unico"


def test_detector_formato_2023_unico():
    assert detectar_formato(_pdfs("2023_unico")) == "unico"


def test_detector_formato_2024_consolidado():
    assert detectar_formato(_pdfs("2024_consolidado")) == "consolidado"


def test_detector_formato_2025_consolidado():
    assert detectar_formato(_pdfs("2025_consolidado")) == "consolidado"


def test_detector_formato_2020_fragmentado():
    assert detectar_formato(_pdfs("2020_fragmentado")) == "fragmentado"


def test_detector_formato_2021_fragmentado():
    assert detectar_formato(_pdfs("2021_fragmentado_4agr")) == "fragmentado"


def test_detector_formato_2024_pasta_misturada():
    assert detectar_formato(_pdfs("2024_pasta_misturada")) == "pasta_mista"


# =============================================================
# splitter
# =============================================================

def _conta_capas(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        capas, _ = capas_reais_doc(doc)
        return len(capas)
    finally:
        doc.close()


def test_splitter_2024_consolidado(tmp_path):
    pdf = _pdfs("2024_consolidado")[0]
    splits = dividir_consolidado(pdf, tmp_path)
    assert len(splits) == 3
    for s in splits:
        assert s.exists()
        assert _conta_capas(s) == 1


def test_splitter_2025_consolidado(tmp_path):
    # Empiricamente: 7 ocorrências de "FATURA AGRUPADORA", mas só 3 capas
    # reais — a página 22 repete o documento da capa da página 21 (boleto).
    pdf = _pdfs("2025_consolidado")[0]
    splits = dividir_consolidado(pdf, tmp_path)
    assert len(splits) == 3
    for s in splits:
        assert s.exists()
        assert _conta_capas(s) == 1


# =============================================================
# merger
# =============================================================

def _paginas(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()


def test_merger_2020_fragmentado(tmp_path):
    pasta = FIXTURES / "2020_fragmentado"
    arquivos = [
        ArquivoIngest(pasta / "1.pdf", "capa"),
        ArquivoIngest(pasta / "2.pdf", "detalhe"),
        ArquivoIngest(pasta / "3.pdf", "detalhe"),
    ]
    merged = fundir_fragmentado(arquivos, tmp_path)
    assert merged.exists()
    # 1 (capa) + 37 (detalhes) + 1 (extra) = 39 páginas.
    assert _paginas(merged) == 39
    # Começa pela capa de 1.pdf.
    capas, _ = capas_reais_doc(fitz.open(str(merged)))
    assert capas and capas[0] == 0


def test_merger_2021_fragmentado(tmp_path):
    pasta = FIXTURES / "2021_fragmentado_4agr"
    arquivos = [
        ArquivoIngest(pasta / "1.pdf", "capa"),
        ArquivoIngest(pasta / "2.pdf", "detalhe"),
    ]
    merged = fundir_fragmentado(arquivos, tmp_path)
    assert merged.exists()
    # 1 (capa) + 5 (detalhes) = 6 páginas.
    assert _paginas(merged) == 6


# =============================================================
# classifier_pasta
# =============================================================

def test_classifier_pasta_2024():
    """
    Pasta mista: 5 PDFs.

    Heurística aplicada: existe um arquivo capa+detalhe completo
    (1-SEMED-FEV-2024.pdf, 46 páginas), por isso ele é suficiente e
    todos os outros vão para descartados.

    usar     = 1 arquivo (capa+detalhe)
    descartar = 4 arquivos (capa solta, 2 relações separadas, 1 ignorar)
    """
    pasta = FIXTURES / "2024_pasta_misturada"
    usar, descartar = classificar_arquivos(pasta)

    # Exatamente 1 arquivo escolhido para uso.
    assert len(usar) == 1
    assert usar[0].papel == "capa+detalhe"

    # Os outros 4 são descartados.
    assert len(descartar) == 4

    # O arquivo escolhido é o capa+detalhe de 46 páginas.
    assert usar[0].caminho.name == "1-SEMED-FEV-2024.pdf"


# =============================================================
# scanner
# =============================================================

def test_scanner_2020_outubro_fragmentado():
    """scan_mes num mês com subpastas por agrupadora deve retornar 3 lotes fragmentados."""
    pasta = _2020 / "10-OUTUBRO-2020"
    if not pasta.exists():
        pytest.skip("FATURAS - SEMED não disponível")
    lotes = scan_mes(pasta)
    assert len(lotes) == 3
    assert all(l.formato == "fragmentado" for l in lotes)
    comps = {l.complemento_provavel for l in lotes}
    assert comps == {"SEMED-I", "SEMED-II", "SEMED-IV"}


def test_scanner_2026_janeiro_unico():
    """scan_mes num mês com PDFs planos deve retornar lotes unico."""
    pasta = _2026 / "JANEIRO - 2026"
    if not pasta.exists():
        pytest.skip("FATURAS - SEMED não disponível")
    lotes = scan_mes(pasta)
    formatos = {l.formato for l in lotes}
    assert formatos == {"unico"}
    comps = {l.complemento_provavel for l in lotes}
    assert "SEMED-I" in comps


# =============================================================
# orquestrador
# =============================================================

def test_orquestrador_2026_referencia(tmp_path):
    """expandir_pasta_historica no JANEIRO-2026 gera 1 lote SEMED-I unico."""
    pasta = _2026 / "JANEIRO - 2026"
    if not pasta.exists():
        pytest.skip("FATURAS - SEMED não disponível")
    lotes = list(expandir_pasta_historica(pasta, tmp_path))
    semed_i = [l for l in lotes if l.complemento_provavel == "SEMED-I"]
    assert len(semed_i) >= 1
    lote = semed_i[0]
    assert lote.formato == "unico"
    assert lote.ano == 2026
    assert lote.pdf_logico is not None
    assert lote.pdf_logico.exists()


def test_orquestrador_2020_outubro(tmp_path):
    """expandir_pasta_historica no OUT-2020 gera 3 lotes fragmentados (I, II, IV)."""
    pasta = _2020 / "10-OUTUBRO-2020"
    if not pasta.exists():
        pytest.skip("FATURAS - SEMED não disponível")
    lotes = list(expandir_pasta_historica(pasta, tmp_path))
    assert len(lotes) == 3
    assert all(l.formato == "fragmentado" for l in lotes)
    comps = {l.complemento_provavel for l in lotes}
    assert comps == {"SEMED-I", "SEMED-II", "SEMED-IV"}
    for lote in lotes:
        assert lote.pdf_logico is not None
        assert lote.pdf_logico.exists()


# =============================================================
# _achar_pastas_mes — estruturas de pasta variadas
# =============================================================
from ingest.orquestrador import _achar_pastas_mes


def test_achar_pastas_mes_meses_com_pdf_direto(tmp_path):
    """
    Estrutura: pasta-de-ano / pasta-de-mes / PDFs diretamente.
    _achar_pastas_mes deve retornar as pastas de mês, não a de ano.
    """
    ano_root = tmp_path / "EQUATORIAL - FATURAS - 2022"
    for nome_mes in ("5_-_MAIO-2022", "6_-_JUNHO-2022"):
        mes_dir = ano_root / nome_mes
        mes_dir.mkdir(parents=True)
        (mes_dir / "fatura.pdf").write_bytes(b"%PDF-dummy")
    resultado = _achar_pastas_mes(ano_root)
    nomes = {p.name for p in resultado}
    assert nomes == {"5_-_MAIO-2022", "6_-_JUNHO-2022"}, (
        f"Esperado {{5_-_MAIO-2022, 6_-_JUNHO-2022}}, obtido {nomes}"
    )


def test_achar_pastas_mes_meses_com_subpastas_agrupadora(tmp_path):
    """
    Estrutura: pasta-de-ano / pasta-de-mes / subpasta-agrupadora / PDFs.
    _achar_pastas_mes deve retornar as pastas de mês (não a de ano nem as de agrupadora).
    """
    ano_root = tmp_path / "EQUATORIAL - FATURAS - 2020"
    for nome_mes in ("OUTUBRO-2020", "NOVEMBRO-2020"):
        for agr in ("SEMED-I", "SEMED-II"):
            agr_dir = ano_root / nome_mes / agr
            agr_dir.mkdir(parents=True)
            (agr_dir / "fatura.pdf").write_bytes(b"%PDF-dummy")
    resultado = _achar_pastas_mes(ano_root)
    nomes = {p.name for p in resultado}
    assert nomes == {"OUTUBRO-2020", "NOVEMBRO-2020"}, (
        f"Esperado meses, obtido {nomes}"
    )


def test_achar_pastas_mes_meses_numericos(tmp_path):
    """
    Estrutura com padrões de nomeação variados (2023–2025).
    """
    ano_root = tmp_path / "EQUATORIAL - FATURAS - 2025"
    for nome_mes in ("FEVEREIRO-2025", "MARCO-2025", "10-OUTUBRO-2025"):
        mes_dir = ano_root / nome_mes
        mes_dir.mkdir(parents=True)
        (mes_dir / "fatura.pdf").write_bytes(b"%PDF-dummy")
    resultado = _achar_pastas_mes(ano_root)
    nomes = {p.name for p in resultado}
    assert nomes == {"FEVEREIRO-2025", "MARCO-2025", "10-OUTUBRO-2025"}, (
        f"Obtido: {nomes}"
    )


def test_achar_pastas_mes_extrai_mes_correto(tmp_path):
    """
    Garante que _extrair_ano_mes extrai mes correto para todos os padrões de nomeação.
    """
    from ingest.scanner import _extrair_ano_mes

    casos = [
        ("OUTUBRO-2020",                2020, 10),
        ("5_-_MAIO-2022",               2022,  5),
        ("6 - JUNHO-2022",              2022,  6),
        ("7-JULHO-2023",                2023,  7),
        ("10-OUTUBRO-SEMED-I-II-2024",  2024, 10),
        ("FEVEREIRO-2025",              2025,  2),
        ("MARCO-2025",                  2025,  3),
    ]
    for nome, ano_esperado, mes_esperado in casos:
        pasta = tmp_path / f"EQUATORIAL - FATURAS - {ano_esperado}" / nome
        pasta.mkdir(parents=True, exist_ok=True)
        ano, mes = _extrair_ano_mes(pasta)
        assert mes == mes_esperado, f"{nome}: esperado mes={mes_esperado}, obtido mes={mes}"
        assert ano == ano_esperado, f"{nome}: esperado ano={ano_esperado}, obtido ano={ano}"
