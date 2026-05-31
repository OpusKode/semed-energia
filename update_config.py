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


def _app_dir() -> Path:
    """Pasta do executável (instalado) ou do projeto (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def obter_token() -> str | None:
    """Lê o token de atualização do ambiente ou de update_token.txt."""
    env = os.getenv("SEMED_UPDATE_TOKEN")
    if env:
        return env.strip()
    arq = _app_dir() / "update_token.txt"
    if arq.exists():
        try:
            # utf-8-sig tolera um BOM (caso o arquivo seja salvo pelo Notepad).
            return arq.read_text(encoding="utf-8-sig").strip() or None
        except Exception:
            return None
    return None
