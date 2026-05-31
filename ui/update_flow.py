"""
Fluxo de auto-atualização COM feedback visual.

Chamado por ui/app.py ANTES de abrir a janela principal. Resolve o problema de
o app parecer "travado": antes ele baixava o pacote (dezenas de MB) em silêncio,
na thread principal, sem nenhuma janela — o usuário via "nada acontecendo" e só
uso de rede. Agora há:

  1. Janela "Verificando atualizações…".
  2. Pergunta ao usuário ANTES de baixar (mostrando o tamanho).
  3. Barra de progresso durante o download (com botão Cancelar), em thread.
  4. Janela "Instalando e reiniciando…".

executar_fluxo_update() -> bool
    True  -> uma atualização foi aplicada; o app deve encerrar (o .bat reinicia).
    False -> seguir o boot normal (sem atualização / recusada / cancelada / erro).

Nunca propaga exceções: qualquer falha resulta em False (app abre normalmente).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal, QEventLoop
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QApplication

import updater


def _mb(n: int) -> str:
    return f"{(n or 0) / 1048576:.0f} MB"


# ─── Threads de trabalho ────────────────────────────────────
class _Tarefa(QThread):
    """Executa uma função sem argumentos numa thread e guarda o retorno."""

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.resultado = None

    def run(self):
        try:
            self.resultado = self._fn()
        except Exception:
            self.resultado = None


class _Download(QThread):
    progresso = Signal(int, int)   # (baixado, total)

    def __init__(self, res):
        super().__init__()
        self._res = res
        self._cancelar = False
        self.zip_path = None

    def cancelar(self):
        self._cancelar = True

    def run(self):
        self.zip_path = updater.baixar(
            self._res,
            on_progress=lambda d, t: self.progresso.emit(d, t),
            cancelado=lambda: self._cancelar,
        )


# ─── Diálogos ───────────────────────────────────────────────
def _rodar_indeterminado(texto: str, fn):
    """Mostra um diálogo 'ocupado' enquanto fn() roda em thread. Retorna fn()."""
    dlg = QProgressDialog(texto, "", 0, 0)
    dlg.setWindowTitle("SEMED Energia")
    dlg.setCancelButton(None)
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)

    tarefa = _Tarefa(fn)
    loop = QEventLoop()
    tarefa.finished.connect(loop.quit)
    tarefa.start()
    dlg.show()
    loop.exec()
    tarefa.wait()
    dlg.close()
    return tarefa.resultado


def _baixar_com_progresso(res):
    total = res.tamanho or 0
    dlg = QProgressDialog(
        f"Baixando atualização {res.versao_remota}…", "Cancelar", 0, max(total, 1)
    )
    dlg.setWindowTitle("SEMED Energia")
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)

    th = _Download(res)

    def on_prog(baixado, tot):
        if tot and dlg.maximum() != tot:
            dlg.setMaximum(tot)
        dlg.setValue(baixado)
        dlg.setLabelText(
            f"Baixando atualização {res.versao_remota}…\n"
            f"{_mb(baixado)} de {_mb(tot or total)}"
        )

    th.progresso.connect(on_prog)
    dlg.canceled.connect(th.cancelar)

    loop = QEventLoop()
    th.finished.connect(loop.quit)
    th.start()
    dlg.show()
    loop.exec()
    th.wait()
    dlg.close()
    return th.zip_path


# ─── Fluxo principal ────────────────────────────────────────
def executar_fluxo_update() -> bool:
    try:
        # 1) Verificar (rápido) — janela "Verificando…"
        res = _rodar_indeterminado("Verificando atualizações…", updater.verificar)
        if res is None or res.erro or not res.disponivel:
            return False

        # 1b) Instalação em pasta protegida (Program Files)? O auto-update não
        # consegue trocar os arquivos sem admin — evita o loop "baixa e não
        # atualiza". Avisa para reinstalar e segue abrindo o app normalmente.
        import sys as _sys
        if getattr(_sys, "frozen", False) and not updater.instalacao_gravavel():
            QMessageBox.information(
                None, "Atualização disponível",
                f"A versão {res.versao_remota} está disponível, mas este "
                "programa está instalado em uma pasta protegida e não pode se "
                "atualizar sozinho.\n\nPeça o instalador mais recente e "
                "reinstale para atualizar.\n\nO programa será aberto normalmente.",
            )
            return False

        # 2) Perguntar ANTES de baixar (mostra o tamanho)
        box = QMessageBox()
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Atualização disponível")
        box.setText(f"Uma nova versão ({res.versao_remota}) está disponível.")
        info = f"Versão atual: {res.versao_local}."
        if res.tamanho:
            info += f"\nTamanho do download: {_mb(res.tamanho)}."
        info += "\n\nDeseja baixar e instalar agora? O programa será reiniciado."
        box.setInformativeText(info)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() != QMessageBox.Yes:
            return False

        # 3) Baixar com barra de progresso (cancelável)
        zip_path = _baixar_com_progresso(res)
        if zip_path is None:
            if res.erro:
                QMessageBox.warning(
                    None, "Atualização",
                    f"Não foi possível baixar a atualização:\n{res.erro}\n\n"
                    "O programa abrirá na versão atual.",
                )
            return False  # cancelado ou erro → abre normal

        # 4) Aplicar + reiniciar — janela "Instalando…"
        dlg = QProgressDialog("Instalando atualização e reiniciando…", "", 0, 0)
        dlg.setWindowTitle("SEMED Energia")
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        QApplication.processEvents()
        aplicado = updater.aplicar_e_reiniciar(zip_path)
        dlg.close()

        if not aplicado:
            QMessageBox.information(
                None, "Atualização",
                "A atualização foi baixada, mas só pode ser aplicada na versão "
                "instalada do programa (não em modo desenvolvimento). "
                "O programa abrirá normalmente.",
            )
            return False
        return True
    except Exception:
        import traceback
        traceback.print_exc()
        return False
