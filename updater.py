"""
Auto-atualização via GitHub Releases (repositório privado).

Fluxo (chamado na inicialização do app):
    1. Consulta a release mais recente na API do GitHub.
    2. Compara a tag (vX.Y.Z) com a versão local (version.__version__).
    3. Se houver versão nova: baixa o .zip anexado à release.
    4. Extrai para uma pasta de staging.
    5. Gera um .bat que, após o app fechar, troca os arquivos e reinicia.

Princípio: NUNCA bloquear o uso do app. Qualquer falha (sem internet,
sem token, erro de rede) é registrada e o app abre normalmente.
Os dados do usuário ficam em %LOCALAPPDATA% e nunca são tocados.
"""
from __future__ import annotations

import logging
import os
import sys
import zipfile
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path

from version import __version__ as VERSAO_LOCAL
import update_config as cfg

log = logging.getLogger("semed.updater")

API = "https://api.github.com"
TIMEOUT = 15


@dataclass
class ResultadoUpdate:
    disponivel: bool = False
    versao_local: str = VERSAO_LOCAL
    versao_remota: str | None = None
    zip_baixado: Path | None = None
    erro: str | None = None


# ─── Comparação de versões ──────────────────────────────────
def _normalizar(tag: str) -> str:
    return tag.lstrip("vV").strip()


def _maior_que(remota: str, local: str) -> bool:
    """remota > local? Usa packaging se disponível; senão, compara tuplas."""
    try:
        from packaging.version import Version
        return Version(remota) > Version(local)
    except Exception:
        def t(v):
            return tuple(int(x) for x in v.split(".") if x.isdigit())
        return t(remota) > t(local)


# ─── GitHub API ─────────────────────────────────────────────
def _headers(octet: bool = False) -> dict:
    h = {
        "Accept": "application/octet-stream" if octet else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "SEMED-Energia-Updater",
    }
    token = cfg.obter_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def obter_release_mais_recente() -> dict | None:
    import requests
    url = f"{API}/repos/{cfg.GITHUB_OWNER}/{cfg.GITHUB_REPO}/releases/latest"
    r = requests.get(url, headers=_headers(), timeout=TIMEOUT)
    if r.status_code == 404:
        log.info("Nenhuma release publicada ainda.")
        return None
    r.raise_for_status()
    return r.json()


def _encontrar_asset(release: dict) -> dict | None:
    for a in release.get("assets", []):
        if a.get("name") == cfg.ASSET_NOME:
            return a
    # fallback: primeiro .zip
    for a in release.get("assets", []):
        if str(a.get("name", "")).endswith(".zip"):
            return a
    return None


def _baixar_asset(asset: dict, destino: Path) -> Path:
    import requests
    url = f"{API}/repos/{cfg.GITHUB_OWNER}/{cfg.GITHUB_REPO}/releases/assets/{asset['id']}"
    with requests.get(url, headers=_headers(octet=True), stream=True,
                      timeout=TIMEOUT, allow_redirects=True) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    return destino


# ─── Verificação (sem aplicar) ──────────────────────────────
def verificar() -> ResultadoUpdate:
    """Checa e baixa (mas não aplica) a atualização, se houver."""
    res = ResultadoUpdate()
    try:
        release = obter_release_mais_recente()
        if not release:
            return res
        tag = _normalizar(release.get("tag_name", ""))
        res.versao_remota = tag
        if not tag or not _maior_que(tag, _normalizar(VERSAO_LOCAL)):
            log.info("Já está na versão mais recente (%s).", VERSAO_LOCAL)
            return res
        asset = _encontrar_asset(release)
        if not asset:
            res.erro = "Release sem pacote .zip anexado."
            log.warning(res.erro)
            return res
        tmp = Path(tempfile.mkdtemp(prefix="semed_update_"))
        zip_path = tmp / asset["name"]
        log.info("Baixando atualização %s...", tag)
        _baixar_asset(asset, zip_path)
        res.zip_baixado = zip_path
        res.disponivel = True
        log.info("Atualização %s baixada em %s", tag, zip_path)
    except Exception as e:
        res.erro = str(e)
        log.warning("Falha ao verificar atualização: %s", e)
    return res


# ─── Aplicação (somente quando empacotado) ──────────────────
def aplicar_e_reiniciar(zip_path: Path) -> bool:
    """
    Extrai o zip para staging e dispara um .bat que, após o app fechar,
    substitui os arquivos da instalação e reinicia. Só faz sentido com
    o app empacotado (frozen). Retorna True se o processo de troca foi
    iniciado (o app deve então encerrar).
    """
    if not getattr(sys, "frozen", False):
        log.info("Modo desenvolvimento: troca de arquivos não aplicada.")
        return False
    try:
        app_dir = Path(sys.executable).parent
        staging = Path(tempfile.mkdtemp(prefix="semed_staging_"))
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(staging)

        # Se o zip tem uma única pasta-raiz, usa o conteúdo dela.
        itens = [p for p in staging.iterdir()]
        raiz = itens[0] if (len(itens) == 1 and itens[0].is_dir()) else staging

        bat = staging / "_aplicar_update.bat"
        exe = app_dir / cfg.EXE_NOME
        bat.write_text(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'robocopy "{raiz}" "{app_dir}" /E /MOVE /R:3 /W:1 /NFL /NDL /NJH /NJS >nul\r\n'
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n',
            encoding="utf-8",
        )
        subprocess.Popen(["cmd", "/c", str(bat)],
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log.info("Troca de arquivos agendada. Encerrando para atualizar.")
        return True
    except Exception as e:
        log.warning("Falha ao aplicar atualização: %s", e)
        return False
