"""
Auto-atualização via GitHub Releases (repositório privado).

Fluxo (chamado na inicialização do app, com janela de progresso):
    1. verificar(): consulta a release mais recente e compara a tag (vX.Y.Z)
       com a versão local. NÃO baixa nada — só diz se há atualização e o tamanho.
    2. (UI) pergunta ao usuário se deseja atualizar.
    3. baixar(res, on_progress, cancelado): baixa o .zip com callback de progresso
       (para a barra) e suporte a cancelamento.
    4. aplicar_e_reiniciar(): extrai para staging e dispara um .bat que, após o
       app fechar, troca os arquivos e reinicia.

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
    asset: dict | None = None        # metadados do .zip na release
    tamanho: int = 0                 # tamanho do .zip em bytes (para a barra)
    zip_baixado: Path | None = None  # preenchido por baixar()
    erro: str | None = None


class _Cancelado(Exception):
    """Sinaliza cancelamento do download pelo usuário."""


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


def _baixar_asset(asset: dict, destino: Path, on_progress=None, cancelado=None) -> Path:
    """
    Baixa o asset em streaming.

    :param on_progress: callable(bytes_baixados:int, bytes_total:int) — chamado a
                        cada bloco; total=0 se desconhecido.
    :param cancelado:   callable() -> bool — se retornar True, aborta (levanta _Cancelado).
    """
    import requests
    url = f"{API}/repos/{cfg.GITHUB_OWNER}/{cfg.GITHUB_REPO}/releases/assets/{asset['id']}"
    total = int(asset.get("size") or 0)
    baixado = 0
    with requests.get(url, headers=_headers(octet=True), stream=True,
                      timeout=TIMEOUT, allow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or total)
        if on_progress:
            on_progress(0, total)
        with open(destino, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if cancelado is not None and cancelado():
                    raise _Cancelado()
                if chunk:
                    f.write(chunk)
                    baixado += len(chunk)
                    if on_progress:
                        on_progress(baixado, total)
    return destino


# ─── Verificação (sem baixar) ───────────────────────────────
def verificar() -> ResultadoUpdate:
    """Checa se há versão mais recente. NÃO baixa nada (ver baixar())."""
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
        res.asset = asset
        res.tamanho = int(asset.get("size") or 0)
        res.disponivel = True
        log.info("Atualização %s disponível (%d bytes).", tag, res.tamanho)
    except Exception as e:
        res.erro = str(e)
        log.warning("Falha ao verificar atualização: %s", e)
    return res


# ─── Download (com progresso) ───────────────────────────────
def baixar(res: ResultadoUpdate, on_progress=None, cancelado=None) -> Path | None:
    """
    Baixa o asset da release já verificada (res.asset). Retorna o caminho do
    .zip, ou None se cancelado/erro (registrando res.erro). Nunca propaga.
    """
    if not res or not res.asset:
        return None
    try:
        tmp = Path(tempfile.mkdtemp(prefix="semed_update_"))
        zip_path = tmp / res.asset["name"]
        log.info("Baixando atualização %s...", res.versao_remota)
        _baixar_asset(res.asset, zip_path, on_progress=on_progress, cancelado=cancelado)
        res.zip_baixado = zip_path
        log.info("Atualização baixada em %s", zip_path)
        return zip_path
    except _Cancelado:
        log.info("Download cancelado pelo usuário.")
        return None
    except Exception as e:
        res.erro = str(e)
        log.warning("Falha ao baixar atualização: %s", e)
        return None


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
