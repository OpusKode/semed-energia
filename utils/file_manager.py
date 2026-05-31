"""
Gestao de arquivos PDF: hash, nomenclatura padronizada e movimentacao.

Padrao: {GRUPO}_{REF}_{DOCUMENTO}_{CONTRATO}_{SUFIXO}.pdf

Exemplos:
    processados/ SEMED-I_REF-2026-01_DOC-610009152708_CC-4000018703.pdf
    duplicados/  SEMED-I_REF-2026-01_DOC-610009152708_CC-4000018703_DUP-HASH.pdf
    erros/       DESCONHECIDO_ERRO_2026-04-14_143022.pdf
"""
import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path


# Sufixos permitidos
SUFIXO_PROCESSADO = ""
SUFIXO_INCOMPLETA = "INCOMPLETA"
SUFIXO_DUP_HASH = "DUP-HASH"
SUFIXO_DUP_DOC = "DUP-DOC"
SUFIXO_ERRO = "ERRO"


def calcular_hash_sha256(caminho: str | Path, bloco: int = 8192) -> str:
    """SHA-256 do conteudo binario do arquivo."""
    sha = hashlib.sha256()
    with open(caminho, "rb") as f:
        for chunk in iter(lambda: f.read(bloco), b""):
            sha.update(chunk)
    return sha.hexdigest()


def formatar_referencia(ref: str | None) -> str:
    """'01/2026' -> '2026-01'. Vazio -> 'SEM-REF'."""
    if not ref:
        return "SEM-REF"
    ref = ref.strip()
    if "/" in ref:
        partes = ref.split("/")
        if len(partes) == 2:
            mes, ano = partes
            return f"{ano.zfill(4)}-{mes.zfill(2)}"
    return ref


def _sanitizar(valor: str) -> str:
    """Remove caracteres invalidos para nome de arquivo."""
    return re.sub(r'[<>:"/\\|?*\s]+', "-", valor).strip("-")


def gerar_nome_padrao(dados_capa: dict | None, sufixo: str = "") -> str:
    """
    Gera o nome do arquivo PDF no padrao do sistema.

    Args:
        dados_capa: dicionario com as chaves 'complemento', 'referencia',
                    'documento' e 'conta_contrato'. Pode ser None se o
                    parsing da capa falhou (fallback com timestamp).
        sufixo: "" | "INCOMPLETA" | "DUP-HASH" | "DUP-DOC" | "ERRO"

    Returns:
        Nome do arquivo (sem caminho), sempre terminado em '.pdf'.
    """
    if dados_capa:
        grupo = _sanitizar((dados_capa.get("complemento") or "DESCONHECIDO"))
        ref = formatar_referencia(dados_capa.get("referencia"))
        documento = _sanitizar(str(dados_capa.get("documento") or "SEM-DOC"))
        contrato = _sanitizar(str(dados_capa.get("conta_contrato") or "SEM-CC"))
        partes = [grupo, f"REF-{ref}", f"DOC-{documento}", f"CC-{contrato}"]
        if sufixo:
            partes.append(sufixo)
    else:
        # Fallback: sem capa, usa timestamp
        agora = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        if sufixo:
            partes = ["DESCONHECIDO", sufixo, agora]
        else:
            partes = ["DESCONHECIDO", agora]

    nome = "_".join(partes) + ".pdf"
    # Ultima sanitizacao para garantir
    nome = re.sub(r'[<>:"/\\|?*]', "_", nome)
    return nome


def _resolver_conflito(destino: Path) -> Path:
    """Se 'destino' ja existe, retorna destino com sufixo _1, _2, ..."""
    if not destino.exists():
        return destino
    base = destino.stem
    ext = destino.suffix
    contador = 1
    while True:
        novo = destino.parent / f"{base}_{contador}{ext}"
        if not novo.exists():
            return novo
        contador += 1


def mover_com_rename(
    origem: str | Path,
    pasta_destino: str | Path,
    dados_capa: dict | None,
    sufixo: str = "",
) -> Path:
    """
    Move o arquivo de origem para pasta_destino renomeando pelo padrao.
    Cria a pasta de destino se nao existir.
    Se ja existir arquivo com o mesmo nome, adiciona contador _1, _2, ...

    Returns:
        Path final do arquivo no destino.
    """
    origem = Path(origem)
    pasta_destino = Path(pasta_destino)
    pasta_destino.mkdir(parents=True, exist_ok=True)

    novo_nome = gerar_nome_padrao(dados_capa, sufixo)
    destino = _resolver_conflito(pasta_destino / novo_nome)

    shutil.move(str(origem), str(destino))
    return destino


def copiar_com_rename(
    origem: str | Path,
    pasta_destino: str | Path,
    dados_capa: dict | None,
    sufixo: str = "",
) -> Path:
    """Mesmo que mover_com_rename, mas copia ao inves de mover (util em testes)."""
    origem = Path(origem)
    pasta_destino = Path(pasta_destino)
    pasta_destino.mkdir(parents=True, exist_ok=True)

    novo_nome = gerar_nome_padrao(dados_capa, sufixo)
    destino = _resolver_conflito(pasta_destino / novo_nome)

    shutil.copy2(str(origem), str(destino))
    return destino
