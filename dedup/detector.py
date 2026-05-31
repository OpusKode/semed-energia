"""
Detector de duplicatas em 3 camadas:

Camada 1 — Hash SHA-256 do arquivo (mais rapida).
Camada 2 — Numero do documento extraido da capa.
Camada 3 — Nota fiscal de cada fatura individual.

A classe nao lida com movimentacao de arquivos; apenas consulta o banco e
retorna metadados da duplicata. A decisao de como rotular/mover fica a
cargo do orquestrador (main.py).
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from db.models import ArquivoProcessado, FaturaAgrupadora, FaturaIndividual
from utils.file_manager import calcular_hash_sha256


# =============================================================
# Estruturas de resultado
# =============================================================

@dataclass
class ResultadoDedup:
    """Resultado da verificacao de duplicata."""
    eh_duplicata: bool
    camada: int | None = None                # 1, 2 ou 3; None se nao duplicata
    tipo: str | None = None                  # 'hash' | 'documento' | 'nota_fiscal'
    documento_existente: str | None = None
    arquivo_existente: str | None = None
    agrupadora_id: int | None = None
    fatura_id: int | None = None
    processado_em: datetime | None = None
    mensagem: str = ""


# =============================================================
# Detector
# =============================================================

class DuplicataDetector:
    """Encapsula a logica das 3 camadas de deteccao."""

    def __init__(self, session: Session):
        self.session = session

    # --- Camada 1: hash do arquivo binario ---
    def verificar_hash(self, caminho_pdf: str | Path) -> ResultadoDedup:
        """Verifica se o SHA-256 deste arquivo ja existe em arquivo_processado."""
        hash_arq = calcular_hash_sha256(caminho_pdf)
        return self.verificar_por_hash(hash_arq)

    def verificar_por_hash(self, hash_sha256: str) -> ResultadoDedup:
        reg = (
            self.session.query(ArquivoProcessado)
            .filter(ArquivoProcessado.hash_sha256 == hash_sha256)
            .first()
        )
        if reg is None:
            return ResultadoDedup(eh_duplicata=False)
        return ResultadoDedup(
            eh_duplicata=True,
            camada=1,
            tipo="hash",
            documento_existente=reg.documento,
            arquivo_existente=reg.nome_original,
            agrupadora_id=reg.agrupadora_id,
            processado_em=reg.processado_em,
            mensagem=(
                f"Arquivo identico ja importado em "
                f"{reg.processado_em:%d/%m/%Y %H:%M} "
                f"(origem: {reg.nome_original})"
            ),
        )

    # --- Camada 2: numero do documento da capa ---
    def verificar_documento(self, documento: str) -> ResultadoDedup:
        """Verifica se o numero do documento da capa ja foi importado."""
        if not documento:
            return ResultadoDedup(eh_duplicata=False)
        reg = (
            self.session.query(FaturaAgrupadora)
            .filter(FaturaAgrupadora.documento == documento)
            .first()
        )
        if reg is None:
            return ResultadoDedup(eh_duplicata=False)
        return ResultadoDedup(
            eh_duplicata=True,
            camada=2,
            tipo="documento",
            documento_existente=reg.documento,
            agrupadora_id=reg.id,
            processado_em=reg.importado_em,
            mensagem=(
                f"Documento {reg.documento} ja foi importado em "
                f"{reg.importado_em:%d/%m/%Y %H:%M} "
                f"(complemento: {reg.complemento})"
            ),
        )

    # --- Camada 3: nota fiscal individual ---
    def verificar_nota_fiscal(self, nota_fiscal: str) -> ResultadoDedup:
        """Verifica se uma nota fiscal ja existe em fatura_individual."""
        if not nota_fiscal:
            return ResultadoDedup(eh_duplicata=False)
        reg = (
            self.session.query(FaturaIndividual)
            .filter(FaturaIndividual.nota_fiscal == nota_fiscal)
            .first()
        )
        if reg is None:
            return ResultadoDedup(eh_duplicata=False)
        return ResultadoDedup(
            eh_duplicata=True,
            camada=3,
            tipo="nota_fiscal",
            fatura_id=reg.id,
            agrupadora_id=reg.agrupadora_id,
            processado_em=reg.importado_em,
            mensagem=(
                f"Nota fiscal {reg.nota_fiscal} ja existe (fatura id={reg.id}, "
                f"unidade: {reg.nome_unidade})"
            ),
        )


# =============================================================
# Funcoes utilitarias (sem DB)
# =============================================================

def estatisticas_dedup(resultados: list[ResultadoDedup]) -> dict:
    """Conta duplicatas por camada. Util para relatorio final."""
    stats = {"camada_1": 0, "camada_2": 0, "camada_3": 0, "novas": 0}
    for r in resultados:
        if not r.eh_duplicata:
            stats["novas"] += 1
        else:
            stats[f"camada_{r.camada}"] += 1
    return stats
