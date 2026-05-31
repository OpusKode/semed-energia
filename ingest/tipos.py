"""Tipos centrais do módulo de ingestão."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Formato = Literal["unico", "fragmentado", "consolidado", "pasta_mista", "desconhecido"]

Papel = Literal[
    "capa", "detalhe", "capa+detalhe", "comprovante", "relatorio", "ignorar"
]


@dataclass
class ArquivoIngest:
    """Um arquivo físico já classificado pelo seu papel na ingestão."""
    caminho: Path
    papel: Papel
    motivo: str = ""  # explicação livre do porquê foi classificado assim

    def __repr__(self) -> str:
        return f"ArquivoIngest({self.caminho.name!r}, papel={self.papel!r})"


@dataclass
class LoteAgrupadora:
    """Um lote pronto para o parser: uma agrupadora = um PDF lógico."""
    ano: int
    mes: int
    complemento_provavel: str       # "SEMED-I", "SEMED-IV", "?" se incerto
    formato: Formato
    arquivos_consumidos: list[ArquivoIngest] = field(default_factory=list)
    arquivos_descartados: list[ArquivoIngest] = field(default_factory=list)
    pdf_logico: Path | None = None  # PDF resultante, pronto para o parser
    avisos: list[str] = field(default_factory=list)
