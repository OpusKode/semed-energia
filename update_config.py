"""
Configuração do mecanismo de auto-atualização.

>>> EDITE OWNER e REPO depois de criar o repositório no GitHub. <<<

O token de acesso (repositório PRIVADO) NÃO fica aqui. Ele é lido, em ordem:
  1. Variável de ambiente  SEMED_UPDATE_TOKEN
  2. Arquivo  update_token.txt  ao lado do executável (incluído pelo instalador)

Use um token *fine-grained* somente-leitura, com acesso APENAS a este
repositório e permissão "Contents: Read-only".
"""
import os
import sys
from pathlib import Path


# ─── EDITAR APÓS CRIAR O REPOSITÓRIO ────────────────────────
GITHUB_OWNER = "OpusKode"                # usuário/organização no GitHub
GITHUB_REPO = "semed-energia"            # nome do repositório no GitHub

# Nome do arquivo .zip anexado a cada release (deve bater com o build/CI).
ASSET_NOME = "SEMED-Energia-windows.zip"

# Nome do executável dentro do pacote (para reiniciar após atualizar).
EXE_NOME = "SEMED Energia.exe"


def _candidatos_token() -> list[Path]:
    """
    Locais onde o token pode estar, em ordem de prioridade.

    No app empacotado, o token é embutido pelo semed.spec em _internal
    (sys._MEIPASS) — então não é preciso copiá-lo manualmente a cada build.
    Também aceitamos o token solto ao lado do exe (compatibilidade) e, em
    desenvolvimento, na raiz do projeto.
    """
    cands: list[Path] = []
    if getattr(sys, "frozen", False):
        cands.append(Path(sys.executable).parent / "update_token.txt")  # ao lado do exe
        mp = getattr(sys, "_MEIPASS", None)
        if mp:
            cands.append(Path(mp) / "update_token.txt")                 # embutido (_internal)
    else:
        cands.append(Path(__file__).parent / "update_token.txt")        # raiz do projeto (dev)
    return cands


def obter_token() -> str | None:
    """Lê o token de atualização do ambiente ou de update_token.txt."""
    env = os.getenv("SEMED_UPDATE_TOKEN")
    if env:
        return env.strip()
    for arq in _candidatos_token():
        try:
            if arq.exists():
                # utf-8-sig tolera um BOM (caso seja salvo pelo Notepad).
                tok = arq.read_text(encoding="utf-8-sig").strip()
                if tok:
                    return tok
        except Exception:
            continue
    return None
