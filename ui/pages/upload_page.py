"""Página de upload e processamento de PDFs com drag & drop."""
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTextEdit, QFileDialog, QProgressBar, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy,
)

from ui.theme import (
    ACCENT, SUCCESS, WARNING, ERROR, TEXT_MUTED, TEXT_SECONDARY,
    TEXT_PRIMARY, BG_CARD, BG_HOVER, BORDER, BG_SIDEBAR,
)
from ui.widgets.icons import lucide_icon, lucide_pixmap
from ui.workers.processor import ProcessadorWorker
from ui.animations import BorderPulse, install_ripple, install_hover_glow


# ─── Constantes de status ────────────────────────────────────

_STATUS_PENDENTE    = "pendente"
_STATUS_PROCESSANDO = "processando"
_STATUS_OK          = "ok"
_STATUS_ERRO        = "erro"
_STATUS_DUPLICADO   = "duplicado"

_CHIP_STYLE = {
    _STATUS_PENDENTE:    (TEXT_MUTED,    "transparent",  ""),
    _STATUS_PROCESSANDO: (ACCENT,        "rgba(217,119,87,0.15)", ACCENT),
    _STATUS_OK:          (SUCCESS,       "rgba(127,174,110,0.18)", SUCCESS),
    _STATUS_ERRO:        (ERROR,         "rgba(212,106,106,0.18)", ERROR),
    _STATUS_DUPLICADO:   (TEXT_SECONDARY,"rgba(156,152,146,0.18)", TEXT_SECONDARY),
}

_CHIP_LABEL = {
    _STATUS_PENDENTE:    "aguardando",
    _STATUS_PROCESSANDO: "⟳  processando",
    _STATUS_OK:          "✓  importado",
    _STATUS_ERRO:        "✗  erro",
    _STATUS_DUPLICADO:   "—  duplicado",
}


def _chip_style(status: str) -> str:
    fg, bg, border = _CHIP_STYLE.get(status, (TEXT_MUTED, "transparent", ""))
    b = f"1px solid {border};" if border else "1px solid transparent;"
    return (
        f"color: {fg}; background: {bg}; border: {b} "
        f"border-radius: 10px; padding: 2px 10px; font-size: 11px; font-weight: 600;"
    )


# ─── Drop zone ───────────────────────────────────────────────

class DropZone(QFrame):
    filesDropped = Signal(object)

    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        self._pulse = BorderPulse(self, color=ACCENT)

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(6)

        self._icon = QLabel()
        self._icon.setPixmap(lucide_pixmap("upload-cloud", color=ACCENT, size=48))
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(self._icon)

        txt = QLabel("Arraste PDFs de fatura aqui")
        txt.setObjectName("DropZoneText")
        txt.setAlignment(Qt.AlignCenter)
        txt.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(txt)

        hint = QLabel("ou clique em  Selecionar arquivos")
        hint.setObjectName("DropZoneHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(hint)

        fmt = QLabel("Equatorial Pará · formatos: único, consolidado, fragmentado, pasta mista")
        fmt.setAlignment(Qt.AlignCenter)
        fmt.setStyleSheet(
            f"border: none; background: transparent; "
            f"color: {TEXT_MUTED}; font-size: 10px; margin-top: 4px;"
        )
        lay.addWidget(fmt)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            self.setObjectName("DropZoneActive")
            self.setStyle(self.style())
            self._pulse.start()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.setObjectName("DropZone")
        self.setStyle(self.style())
        self._pulse.stop()

    def dropEvent(self, e: QDropEvent):
        self.setObjectName("DropZone")
        self.setStyle(self.style())
        self._pulse.stop()
        paths = [
            Path(url.toLocalFile())
            for url in e.mimeData().urls()
            if Path(url.toLocalFile()).suffix.lower() == ".pdf"
        ]
        if paths:
            self.filesDropped.emit(paths)


# ─── Card de resultado ───────────────────────────────────────

class _ResultCard(QFrame):
    def __init__(self, label: str, cor: str):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        self._val = QLabel("—")
        self._val.setStyleSheet(
            f"color: {cor}; font-size: 26px; font-weight: 700; background: transparent;"
        )
        lbl = QLabel(label.upper())
        lbl.setObjectName("CardLabel")
        lay.addWidget(self._val)
        lay.addWidget(lbl)

    def set_value(self, v):
        self._val.setText(str(v))


# ─── Página principal ────────────────────────────────────────

class UploadPage(QWidget):
    """Página de upload + processamento de PDFs de fatura."""

    dadosProcessados = Signal(object)
    bancoAtualizado  = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.pdfs: list[Path] = []
        self.worker: ProcessadorWorker | None = None
        self._status_por_pdf: dict[str, str] = {}   # nome → status
        self._build()

    # ─── Construção ──────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        # Cabeçalho
        titulo = QLabel("Processar faturas")
        titulo.setObjectName("PageTitle")
        sub = QLabel(
            "Arraste PDFs da Equatorial Pará ou selecione manualmente, "
            "depois clique em Processar para importar ao banco."
        )
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        root.addWidget(titulo)
        root.addWidget(sub)

        # Splitter vertical: topo (drop + fila) | baixo (progresso + log)
        split = QSplitter(Qt.Vertical)

        # ── Painel superior ──────────────────────────────────
        top = QWidget()
        top_lay = QVBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(10)

        # Drop zone
        self.drop = DropZone()
        self.drop.filesDropped.connect(self._add_files)
        top_lay.addWidget(self.drop)

        # Barra de ações
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_select = QPushButton("  Selecionar arquivos…")
        self.btn_select.setIcon(lucide_icon("folder-open", size=15))
        self.btn_select.setIconSize(QSize(15, 15))
        self.btn_select.clicked.connect(self._pick_files)

        self.btn_clear = QPushButton("  Limpar")
        self.btn_clear.setIcon(lucide_icon("trash-2", size=15))
        self.btn_clear.setIconSize(QSize(15, 15))
        self.btn_clear.clicked.connect(self._clear)

        self.btn_reprocess = QPushButton("  Reprocessar…")
        self.btn_reprocess.setIcon(lucide_icon("refresh-cw", size=15))
        self.btn_reprocess.setIconSize(QSize(15, 15))
        self.btn_reprocess.setToolTip(
            "Seleciona PDFs da pasta processados/ e reimporta, "
            "removendo o documento já existente no banco."
        )
        self.btn_reprocess.clicked.connect(self._start_reprocess)
        self.btn_reprocess.setEnabled(False)

        self.btn_cancel = QPushButton("  Cancelar")
        self.btn_cancel.setIcon(lucide_icon("x", size=15))
        self.btn_cancel.setIconSize(QSize(15, 15))
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.setVisible(False)

        self.btn_process = QPushButton("  Processar")
        self.btn_process.setObjectName("Primary")
        self.btn_process.setIcon(lucide_icon(
            "play", color="#1C1B1A", size=15, disabled_color=TEXT_MUTED,
        ))
        self.btn_process.setIconSize(QSize(15, 15))
        self.btn_process.setCursor(Qt.PointingHandCursor)
        self.btn_process.setMinimumWidth(120)
        self.btn_process.clicked.connect(self._start)
        self.btn_process.setEnabled(False)
        install_ripple(self.btn_process, color="#FFFFFF")
        install_hover_glow(self.btn_process, color=ACCENT, blur=24)

        # Contador de arquivos
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        btn_row.addWidget(self.btn_select)
        btn_row.addWidget(self.btn_clear)
        btn_row.addWidget(self.btn_reprocess)
        btn_row.addWidget(self.lbl_count)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_process)
        top_lay.addLayout(btn_row)

        # Tabela de fila de arquivos
        self._build_tabela(top_lay)

        split.addWidget(top)

        # ── Painel inferior ──────────────────────────────────
        bot = QWidget()
        bot_lay = QVBoxLayout(bot)
        bot_lay.setContentsMargins(0, 0, 0, 0)
        bot_lay.setSpacing(8)

        # Barra de progresso (oculta até processar)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background: {BG_HOVER};
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT};
                border-radius: 3px;
            }}
        """)
        self.lbl_prog_detalhe = QLabel("")
        self.lbl_prog_detalhe.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px;"
        )
        self.lbl_prog_detalhe.setVisible(False)

        prog_row = QHBoxLayout()
        prog_row.addWidget(self.progress, 1)
        prog_row.addWidget(self.lbl_prog_detalhe, 0)

        # Cards de resultado (ocultos até o fim)
        self._result_row = QWidget()
        self._result_row.setVisible(False)
        rr_lay = QHBoxLayout(self._result_row)
        rr_lay.setContentsMargins(0, 0, 0, 0)
        rr_lay.setSpacing(10)
        self.card_imp  = _ResultCard("Importados",  SUCCESS)
        self.card_fat  = _ResultCard("Faturas",     ACCENT)
        self.card_dup  = _ResultCard("Duplicadas",  TEXT_SECONDARY)
        self.card_err  = _ResultCard("Erros",       ERROR)
        for c in (self.card_imp, self.card_fat, self.card_dup, self.card_err):
            rr_lay.addWidget(c, 1)

        # Cabeçalho do log
        log_header = QHBoxLayout()
        log_lbl = QLabel("Log de execução")
        log_lbl.setObjectName("SectionTitle")
        self.lbl_log_status = QLabel("")
        self.lbl_log_status.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px;"
        )
        log_header.addWidget(log_lbl)
        log_header.addStretch()
        log_header.addWidget(self.lbl_log_status)

        self.log = QTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)

        bot_lay.addLayout(prog_row)
        bot_lay.addWidget(self._result_row)
        bot_lay.addLayout(log_header)
        bot_lay.addWidget(self.log, 1)

        split.addWidget(bot)
        split.setSizes([300, 380])
        root.addWidget(split, 1)

    def _build_tabela(self, parent_lay: QVBoxLayout):
        """Tabela de fila com colunas: ícone·nome | tamanho | status."""
        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeader(self.tabela.horizontalHeader())
        self.tabela.horizontalHeader().setVisible(True)
        self.tabela.setHorizontalHeaderLabels(["Arquivo", "Tamanho", "Status"])
        self.tabela.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabela.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tabela.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setMinimumHeight(100)
        self.tabela.setMaximumHeight(220)
        self.tabela.setShowGrid(False)
        parent_lay.addWidget(self.tabela)

    # ─── Gestão da fila ──────────────────────────────────────

    def _add_files(self, paths):
        for p in paths:
            if p not in self.pdfs:
                self.pdfs.append(p)
                self._status_por_pdf[p.name] = _STATUS_PENDENTE
                self._add_row(p)
        self._atualizar_botoes()

    def _add_row(self, p: Path):
        row = self.tabela.rowCount()
        self.tabela.insertRow(row)
        self.tabela.setRowHeight(row, 32)

        # Col 0 — nome
        nome_item = QTableWidgetItem(
            lucide_icon("file-text", size=14), f"  {p.name}"
        )
        nome_item.setToolTip(str(p))
        self.tabela.setItem(row, 0, nome_item)

        # Col 1 — tamanho
        try:
            size_kb = p.stat().st_size / 1024
            size_txt = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        except OSError:
            size_txt = "—"
        sz_item = QTableWidgetItem(size_txt)
        sz_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sz_item.setForeground(QColor(TEXT_MUTED))
        self.tabela.setItem(row, 1, sz_item)

        # Col 2 — status chip
        self._set_status_chip(row, _STATUS_PENDENTE)

    def _set_status_chip(self, row: int, status: str):
        chip = QLabel(_CHIP_LABEL.get(status, status))
        chip.setStyleSheet(_chip_style(status))
        chip.setAlignment(Qt.AlignCenter)
        self.tabela.setCellWidget(row, 2, chip)

    def _atualizar_status_pdf(self, nome: str, status: str):
        """Atualiza o chip da linha cujo nome de arquivo bate."""
        self._status_por_pdf[nome] = status
        for row in range(self.tabela.rowCount()):
            item = self.tabela.item(row, 0)
            if item and item.text().strip() == nome:
                self._set_status_chip(row, status)
                break

    def _clear(self):
        self.pdfs.clear()
        self._status_por_pdf.clear()
        self.tabela.setRowCount(0)
        self.log.clear()
        self.progress.setVisible(False)
        self.lbl_prog_detalhe.setVisible(False)
        self._result_row.setVisible(False)
        self.lbl_log_status.setText("")
        self._atualizar_botoes()

    def _atualizar_botoes(self):
        n = len(self.pdfs)
        self.btn_process.setEnabled(n > 0)
        self.btn_reprocess.setEnabled(n > 0)
        if n == 0:
            self.lbl_count.setText("")
        elif n == 1:
            self.lbl_count.setText("1 arquivo")
        else:
            self.lbl_count.setText(f"{n} arquivos")

    # ─── Seleção manual ──────────────────────────────────────

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Selecione PDFs de fatura", "", "PDFs (*.pdf)"
        )
        if files:
            self._add_files([Path(f) for f in files])

    # ─── Processamento ───────────────────────────────────────

    def _start(self, reprocessar: bool = False):
        if not self.pdfs:
            return

        # Reseta chips para "pendente"
        for row in range(self.tabela.rowCount()):
            self._set_status_chip(row, _STATUS_PENDENTE)
        for k in self._status_por_pdf:
            self._status_por_pdf[k] = _STATUS_PENDENTE

        self.btn_process.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.btn_reprocess.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._result_row.setVisible(False)

        self.log.clear()
        self.progress.setRange(0, len(self.pdfs))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_prog_detalhe.setText("Iniciando…")
        self.lbl_prog_detalhe.setVisible(True)

        if reprocessar:
            self._append_log("♻ Modo reprocessamento: documentos existentes serão removidos.", "warn")

        self.worker = ProcessadorWorker(
            list(self.pdfs),
            persistir=True,
            reprocessar_documentos=reprocessar,
        )
        self.worker.log.connect(self._on_log)
        self.worker.progresso.connect(self._on_prog)
        self.worker.fatura_progresso.connect(self._on_fat_prog)
        self.worker.arquivo_concluido.connect(self._on_arquivo)
        self.worker.concluido.connect(self._on_done)
        self.worker.banco_atualizado.connect(self.bancoAtualizado.emit)
        self.worker.start()

    def _start_reprocess(self):
        from config import PASTA_PROCESSADOS
        pasta = str(PASTA_PROCESSADOS) if PASTA_PROCESSADOS.exists() else ""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Selecione PDFs para reprocessar", pasta, "PDFs (*.pdf)"
        )
        if not files:
            return
        self.pdfs = [Path(f) for f in files]
        self.tabela.setRowCount(0)
        self._status_por_pdf.clear()
        for p in self.pdfs:
            self._status_por_pdf[p.name] = _STATUS_PENDENTE
            self._add_row(p)
        self._atualizar_botoes()
        self._start(reprocessar=True)

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self._append_log("⏹ Cancelamento solicitado…", "warn")
            self.worker.cancelar()
            self.btn_cancel.setEnabled(False)

    def stop_worker_blocking(self, timeout_ms: int = 5000) -> bool:
        if self.worker is None or not self.worker.isRunning():
            return True
        self.worker.cancelar()
        return self.worker.wait(timeout_ms)

    # ─── Slots do worker ─────────────────────────────────────

    def _on_log(self, texto: str, nivel: str):
        self._append_log(texto, nivel)

    def _on_prog(self, atual: int, total: int):
        self.progress.setValue(atual)
        # Atualiza chip do arquivo que acabou de ser processado
        if 0 < atual <= len(self.pdfs):
            pdf = self.pdfs[atual - 1]
            status = self._status_por_pdf.get(pdf.name, _STATUS_OK)
            if status == _STATUS_PENDENTE:
                status = _STATUS_OK
            self._atualizar_status_pdf(pdf.name, status)
        # Marca o próximo como "processando"
        if atual < total:
            prox = self.pdfs[atual]
            self._atualizar_status_pdf(prox.name, _STATUS_PROCESSANDO)
            self.lbl_prog_detalhe.setText(
                f"{atual + 1}/{total} — {prox.name}"
            )
        else:
            self.lbl_prog_detalhe.setText(f"Concluído  {total}/{total}")

    def _on_fat_prog(self, pdf: str, extraidas: int, esperadas: int):
        if esperadas:
            self._append_log(f"  {pdf}: {extraidas}/{esperadas} faturas", "info")

    def _on_arquivo(self, item: dict):
        # Marca status do arquivo no chip
        nome = Path(item.get("pdf", "")).name
        if item.get("erro"):
            self._atualizar_status_pdf(nome, _STATUS_ERRO)
        elif item.get("duplicado"):
            self._atualizar_status_pdf(nome, _STATUS_DUPLICADO)
        else:
            self._atualizar_status_pdf(nome, _STATUS_OK)
        self.dadosProcessados.emit(item)

    def _on_done(self, stats: dict):
        # Restaura botões
        self.btn_process.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.btn_reprocess.setEnabled(len(self.pdfs) > 0)
        self.btn_cancel.setVisible(False)

        # Esconde barra de progresso após breve delay
        QTimer.singleShot(1200, lambda: self.progress.setVisible(False))
        QTimer.singleShot(1200, lambda: self.lbl_prog_detalhe.setVisible(False))

        # Atualiza cards de resultado
        dup = (stats.get("duplicados_hash", 0)
               + stats.get("duplicados_doc", 0)
               + stats.get("duplicados_nf", 0))
        self.card_imp.set_value(stats.get("importados", 0))
        self.card_fat.set_value(stats.get("faturas_total", 0))
        self.card_dup.set_value(dup)
        self.card_err.set_value(stats.get("erros", 0))
        self._result_row.setVisible(True)

        # Log resumo
        self._append_log("", "info")
        self._append_log("═══ RELATÓRIO FINAL ═══", "title")
        nv = "ok" if stats.get("importados") else "info"
        self._append_log(
            f"Importados: {stats['importados']}  ·  "
            f"Faturas: {stats['faturas_total']}  ·  "
            f"Duplicadas: {dup}  ·  "
            f"Erros: {stats['erros']}  ·  "
            f"Warnings: {stats['warnings']}",
            nv,
        )
        if stats.get("persistido"):
            self._append_log("✓ Dados gravados no banco com sucesso.", "ok")

        n_ok = stats.get("importados", 0)
        n_err = stats.get("erros", 0)
        if n_ok and not n_err:
            self.lbl_log_status.setText(f"✓ {n_ok} importado(s)")
            self.lbl_log_status.setStyleSheet(f"color: {SUCCESS}; font-size: 11px;")
        elif n_err:
            self.lbl_log_status.setText(f"{n_ok} ok · {n_err} erro(s)")
            self.lbl_log_status.setStyleSheet(f"color: {WARNING}; font-size: 11px;")

    # ─── Helper de log ───────────────────────────────────────

    def _append_log(self, texto: str, nivel: str):
        color = {
            "ok":    SUCCESS,
            "warn":  WARNING,
            "error": ERROR,
            "title": ACCENT,
            "info":  TEXT_PRIMARY,
        }.get(nivel, TEXT_PRIMARY)
        ts = datetime.now().strftime("%H:%M:%S")
        if not texto:
            self.log.append("")
            return
        self.log.append(
            f'<span style="color:{TEXT_MUTED}">[{ts}]</span> '
            f'<span style="color:{color}">{texto}</span>'
        )
