"""Janela principal: sidebar Claude-like + QStackedWidget com as 4 paginas."""
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer, QEvent
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame,
    QLabel, QStackedWidget, QButtonGroup, QStatusBar, QFileDialog,
    QMessageBox,
)

from ui.theme import ACCENT, TEXT_SECONDARY, SUCCESS, WARNING, ERROR, TEXT_MUTED
from ui.widgets.icons import lucide_icon
from ui.animations import (
    AnimatedBackground, AnimatedStackedWidget,
    install_ripple, install_hover_glow, fade_in,
)
from ui.widgets.title_bar import TitleBar
from ui.pages.upload_page import UploadPage
from ui.pages.agrupadoras_page import AgrupadorasPage
from ui.pages.dashboard_page import DashboardPage
from ui.pages.validacao_page import ValidacaoPage
from ui.pages.fatura_detalhe_page import FaturaDetalhePage
from ui.pages.unidade_page import UnidadePage
from ui.workers.db_loader import DbLoaderWorker
from ui.workers.export_worker import ExportPowerBIWorker, ExportRawWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SEMED Energia — Importador de Faturas")
        self.setMinimumSize(1180, 760)
        # Janela sem frame nativo (barra de titulo minimalista propria).
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self._resize_margin = 6
        self._resize_edge: str | None = None
        self._resize_start_geo = None
        self._resize_start_pos = None
        self.setMouseTracking(True)
        self._db_loader: DbLoaderWorker | None = None
        self._export_worker: ExportPowerBIWorker | None = None
        self._export_raw_worker: ExportRawWorker | None = None
        # Rastreia de onde veio a navegacao para o detalhe da fatura
        # para que o botao "Voltar" retorne para a pagina de origem.
        self._detalhe_origem_idx: int = 1
        self._build()
        # carregar banco logo depois da primeira volta do event loop
        QTimer.singleShot(100, self._carregar_do_banco)

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)

        # ---- Fundo animado (orbes de luz flutuando) ----
        self._bg = AnimatedBackground(central)
        self._bg.lower()
        self._bg.setGeometry(central.rect())
        central.installEventFilter(self)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Barra de titulo customizada (Claude-style) ----
        self.title_bar = TitleBar(self, "SEMED Energia — Importador de Faturas")
        root.addWidget(self.title_bar)

        # Corpo: sidebar + stack (horizontal)
        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        root.addWidget(body, 1)

        # ---- Sidebar ----
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        # Cabecalho com logo grande centralizada + texto embaixo
        assets = Path(__file__).parent / "assets"
        icon_png = assets / "icon.png"
        icon_ico = assets / "icon.ico"
        icon_path = icon_png if icon_png.exists() else (
            icon_ico if icon_ico.exists() else None
        )

        header = QWidget()
        hlay = QVBoxLayout(header)
        hlay.setContentsMargins(14, 24, 14, 10)
        hlay.setSpacing(8)

        if icon_path is not None:
            logo = QLabel()
            pm = QPixmap(str(icon_path)).scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            logo.setPixmap(pm)
            logo.setAlignment(Qt.AlignCenter)
            hlay.addWidget(logo)

        titulo = QLabel("SEMED Energia")
        titulo.setObjectName("SidebarTitle")
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet("padding: 0;")
        sub = QLabel("Equatorial Pará · v1")
        sub.setObjectName("SidebarSubtitle")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("padding: 0 0 6px 0;")
        hlay.addWidget(titulo)
        hlay.addWidget(sub)
        sb_lay.addWidget(header)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.upload_page = UploadPage()
        self.agrupadoras_page = AgrupadorasPage()
        self.unidade_page = UnidadePage()
        self.dashboard_page = DashboardPage()
        self.validacao_page = ValidacaoPage()
        self.detalhe_page = FaturaDetalhePage()

        self.stack = AnimatedStackedWidget()
        self.stack.addWidget(self.upload_page)          # 0
        self.stack.addWidget(self.agrupadoras_page)     # 1
        self.stack.addWidget(self.unidade_page)         # 2
        self.stack.addWidget(self.dashboard_page)       # 3
        self.stack.addWidget(self.validacao_page)       # 4
        self.stack.addWidget(self.detalhe_page)         # 5 (sem item no sidebar)

        items = [
            ("upload-cloud", "Processar",   0),
            ("layers",       "Agrupadoras", 1),
            ("building-2",   "Unidades",    2),
            ("bar-chart-3",  "Dashboard",   3),
            ("check-circle", "Validação",   4),
        ]
        for i, (icon_name, label, idx) in enumerate(items):
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(lucide_icon(icon_name, color=TEXT_SECONDARY, size=18))
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _=False, i=idx: self.stack.setCurrentIndex(i))
            install_ripple(btn, color=ACCENT)
            self.btn_group.addButton(btn, idx)
            sb_lay.addWidget(btn)
            if i == 0:
                btn.setChecked(True)

        sb_lay.addStretch()

        # Botao exportar para Power BI
        self.btn_export = QPushButton("  Exportar p/ Power BI")
        self.btn_export.setObjectName("NavButton")
        self.btn_export.setIcon(lucide_icon("download", color=TEXT_SECONDARY, size=16))
        self.btn_export.setIconSize(QSize(16, 16))
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._exportar_powerbi)
        install_ripple(self.btn_export, color=ACCENT)
        install_hover_glow(self.btn_export, color=ACCENT, blur=22)
        sb_lay.addWidget(self.btn_export)

        # Botao exportar bruto (CSV por tabela ou XLSX bruto)
        self.btn_export_raw = QPushButton("  Exportar bruto (CSV/XLSX)")
        self.btn_export_raw.setObjectName("NavButton")
        self.btn_export_raw.setIcon(
            lucide_icon("file-text", color=TEXT_SECONDARY, size=16)
        )
        self.btn_export_raw.setIconSize(QSize(16, 16))
        self.btn_export_raw.setCursor(Qt.PointingHandCursor)
        self.btn_export_raw.setToolTip(
            "Exporta as tabelas do banco: escolha um .xlsx para arquivo unico "
            "ou um diretorio para um CSV por tabela."
        )
        self.btn_export_raw.clicked.connect(self._exportar_raw)
        install_ripple(self.btn_export_raw, color=ACCENT)
        sb_lay.addWidget(self.btn_export_raw)

        # Botao recarregar banco
        self.btn_reload = QPushButton("  Recarregar banco")
        self.btn_reload.setObjectName("NavButton")
        self.btn_reload.setIcon(lucide_icon("refresh-cw", color=TEXT_SECONDARY, size=16))
        self.btn_reload.setIconSize(QSize(16, 16))
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.clicked.connect(self._carregar_do_banco)
        install_ripple(self.btn_reload, color=ACCENT)
        sb_lay.addWidget(self.btn_reload)

        footer = QLabel("Anthropic Cowork · Claude · Opuskode")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(f"color: #6E6B67; padding: 14px 10px; font-size: 10px;")
        sb_lay.addWidget(footer)

        body_lay.addWidget(sidebar)
        body_lay.addWidget(self.stack, 1)

        # Status bar com indicador de DB
        status = QStatusBar()
        status.setStyleSheet(
            f"QStatusBar {{ background: #1C1B1A; color: {TEXT_MUTED}; "
            f"border-top: 1px solid #3A3937; font-size: 11px; }}"
        )
        self.setStatusBar(status)
        self.lbl_status_db = QLabel("Banco: aguardando…")
        status.addWidget(self.lbl_status_db)

        # ---- Fios (conectar sinais) ----
        self.upload_page.dadosProcessados.connect(self._on_item_processado)
        self.upload_page.bancoAtualizado.connect(self._carregar_do_banco)
        self.agrupadoras_page.faturaSelecionada.connect(
            lambda f, c: self._abrir_detalhe(f, c, origem_idx=1)
        )
        self.unidade_page.faturaSelecionada.connect(
            lambda f, c: self._abrir_detalhe(f, c, origem_idx=2)
        )
        self.detalhe_page.voltar.connect(self._voltar_do_detalhe)
        self.detalhe_page.verUnidade.connect(self._abrir_unidade)
        # Clique numa barra do "Top unidades" do Dashboard -> abre o
        # detalhe da unidade. A `key` emitida e a instalacao (preferencial);
        # se nao vier, recebemos o nome e tentamos resolver via fallback.
        self.dashboard_page.unidade_clicada.connect(self._abrir_unidade_do_dashboard)
        self.dashboard_page.alertaNavegar.connect(self._on_alerta_navegar)

    # =========================================================
    # Resize por bordas (janela frameless)
    # =========================================================
    def _edge_at(self, pos):
        m = self._resize_margin
        r = self.rect()
        left = pos.x() <= m
        right = pos.x() >= r.width() - m
        top = pos.y() <= m
        bottom = pos.y() >= r.height() - m
        if top and left: return "tl"
        if top and right: return "tr"
        if bottom and left: return "bl"
        if bottom and right: return "br"
        if left: return "l"
        if right: return "r"
        if top: return "t"
        if bottom: return "b"
        return None

    def _cursor_for_edge(self, edge):
        return {
            "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
            "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
            "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
            "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
        }.get(edge, Qt.ArrowCursor)

    def mouseMoveEvent(self, ev):
        if self.isMaximized():
            self.unsetCursor()
            return super().mouseMoveEvent(ev)
        if self._resize_edge and ev.buttons() & Qt.LeftButton:
            gp = ev.globalPosition().toPoint()
            dx = gp.x() - self._resize_start_pos.x()
            dy = gp.y() - self._resize_start_pos.y()
            g = self._resize_start_geo
            x, y, w, h = g.x(), g.y(), g.width(), g.height()
            minw, minh = self.minimumWidth(), self.minimumHeight()
            edge = self._resize_edge
            if "l" in edge:
                new_w = max(minw, w - dx); x += (w - new_w); w = new_w
            if "r" in edge:
                w = max(minw, w + dx)
            if "t" in edge:
                new_h = max(minh, h - dy); y += (h - new_h); h = new_h
            if "b" in edge:
                h = max(minh, h + dy)
            self.setGeometry(x, y, w, h)
            return
        edge = self._edge_at(ev.position().toPoint())
        self.setCursor(self._cursor_for_edge(edge))
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._edge_at(ev.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = ev.globalPosition().toPoint()
                return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._resize_edge = None
        self.unsetCursor()
        super().mouseReleaseEvent(ev)

    def eventFilter(self, obj, ev):
        # Mantem o widget de fundo cobrindo a area central
        if ev.type() == QEvent.Resize and obj is self.centralWidget():
            if hasattr(self, "_bg") and self._bg is not None:
                self._bg.setGeometry(obj.rect())
                self._bg.lower()
        return super().eventFilter(obj, ev)

    def _on_item_processado(self, item: dict):
        """Distribui o item para as outras paginas."""
        self.agrupadoras_page.adicionar_item(item)
        self.unidade_page.adicionar_item(item)
        self.dashboard_page.adicionar_item(item)
        self.validacao_page.adicionar_item(item)

    def _abrir_detalhe(self, fatura: dict, capa: dict, origem_idx: int = 1):
        """Exibe a pagina de detalhe para a fatura selecionada.

        :param origem_idx: indice no stack para onde voltar (1 = Agrupadoras,
                           2 = Unidades). Usado pelo botao Voltar.
        """
        self._detalhe_origem_idx = origem_idx
        self.detalhe_page.set_fatura(fatura, capa)
        chk = self.btn_group.checkedButton()
        if chk is not None:
            self.btn_group.setExclusive(False)
            chk.setChecked(False)
            self.btn_group.setExclusive(True)
        self.stack.setCurrentWidget(self.detalhe_page)

    def _voltar_do_detalhe(self):
        """Botao Voltar: retorna para a pagina de origem (agrupadoras ou unidades)."""
        self.stack.setCurrentIndex(self._detalhe_origem_idx)
        btn = self.btn_group.button(self._detalhe_origem_idx)
        if btn:
            btn.setChecked(True)

    def _abrir_unidade(self, instalacao: str):
        """Ver historico da unidade a partir da pagina de detalhe."""
        self.unidade_page.mostrar_instalacao(instalacao)
        self.stack.setCurrentWidget(self.unidade_page)
        btn = self.btn_group.button(2)
        if btn:
            btn.setChecked(True)

    def _on_alerta_navegar(self, tipo: str, chave: str):
        """Navega para instalacao ou agrupadora a partir de um alerta do Dashboard."""
        if not chave:
            return
        if tipo == "instalacao":
            self._abrir_unidade(chave)
        elif tipo == "agrupadora":
            self.stack.setCurrentIndex(1)
            btn = self.btn_group.button(1)
            if btn:
                btn.setChecked(True)

    def _abrir_unidade_do_dashboard(self, chave: str):
        """Resolve a `chave` emitida pelo dashboard e abre a UnidadePage.

        `chave` e normalmente a instalacao; caso o worker nao tenha
        conseguido preencher, recebemos o nome da unidade e resolvemos
        aqui buscando a primeira instalacao com esse nome.
        """
        if not chave:
            return
        mapa = getattr(self.unidade_page, "por_instalacao", {})
        if chave in mapa:
            self._abrir_unidade(chave)
            return
        alvo = chave.strip().lower()
        for inst, info in mapa.items():
            if (info.get("unidade") or "").strip().lower() == alvo:
                self._abrir_unidade(inst)
                return

    # =========================================================
    # Carregamento automatico do banco
    # =========================================================

    def _carregar_do_banco(self):
        """Dispara carga assincrona do banco (via QThread)."""
        if self._db_loader is not None and self._db_loader.isRunning():
            return
        self.btn_reload.setEnabled(False)
        self.lbl_status_db.setText("Banco: conectando…")
        self.lbl_status_db.setStyleSheet(f"color: {TEXT_MUTED};")

        # Limpar dados em memoria para nao duplicar
        self._limpar_paginas()

        self._db_loader = DbLoaderWorker()
        self._db_loader.iniciou.connect(self._on_db_iniciou)
        self._db_loader.item_carregado.connect(self._on_db_item)
        self._db_loader.concluido.connect(self._on_db_concluido)
        self._db_loader.erro.connect(self._on_db_erro)
        self._db_loader.start()

    def _limpar_paginas(self):
        """Remove dados carregados previamente nas paginas."""
        self.agrupadoras_page.dados.clear()
        self.agrupadoras_page.model_ag.set_rows([])
        self.agrupadoras_page.model_fat.set_rows([])
        self.agrupadoras_page._arvore_dados = {}
        if hasattr(self.unidade_page, "clear_all"):
            self.unidade_page.clear_all()
        if hasattr(self.dashboard_page, "clear_all"):
            self.dashboard_page.clear_all()
        if hasattr(self.validacao_page, "clear_all"):
            self.validacao_page.clear_all()

    def _on_db_iniciou(self, total: int):
        if total == 0:
            self.lbl_status_db.setText("Banco: vazio (nenhuma agrupadora importada)")
        else:
            self.lbl_status_db.setText(f"Banco: carregando {total} agrupadora(s)…")

    def _on_db_item(self, item: dict):
        # Reusa o mesmo fluxo do processamento
        self._on_item_processado(item)

    def _on_db_concluido(self, n: int, tempo_ms: int):
        self.btn_reload.setEnabled(True)
        total_fat = sum(len(it.get("faturas", [])) for it in self.agrupadoras_page.dados)
        self.lbl_status_db.setText(
            f"Banco: {n} agrupadora(s) · {total_fat} fatura(s) · "
            f"carga em {tempo_ms} ms"
        )
        self.lbl_status_db.setStyleSheet(f"color: {SUCCESS};")

    def _on_db_erro(self, msg: str):
        self.btn_reload.setEnabled(True)
        self.lbl_status_db.setText(f"Banco: offline — {msg.splitlines()[0]}")
        self.lbl_status_db.setStyleSheet(f"color: {WARNING};")

    # =========================================================
    # Exportacao Power BI
    # =========================================================

    def _exportar_powerbi(self):
        if self._export_worker is not None and self._export_worker.isRunning():
            return

        from datetime import datetime
        default_name = f"semed_energia_{datetime.now():%Y%m%d_%H%M}.xlsx"
        destino, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar para Power BI",
            default_name,
            "Arquivo Excel (*.xlsx)",
        )
        if not destino:
            return
        if not destino.lower().endswith(".xlsx"):
            destino += ".xlsx"

        self.btn_export.setEnabled(False)
        self.lbl_status_db.setText("Exportando para Power BI…")
        self.lbl_status_db.setStyleSheet(f"color: {TEXT_MUTED};")

        self._export_worker = ExportPowerBIWorker(destino)
        self._export_worker.progresso.connect(self._on_export_prog)
        self._export_worker.concluido.connect(self._on_export_done)
        self._export_worker.erro.connect(self._on_export_erro)
        self._export_worker.start()

    def _on_export_prog(self, i: int, total: int, nome: str):
        self.lbl_status_db.setText(f"Exportando {i+1}/{total}: {nome}…")

    def _on_export_done(self, stats: dict):
        self.btn_export.setEnabled(True)
        self.lbl_status_db.setText(
            f"✓ Exportado: {stats['sheets']} sheets · {stats['linhas']} linhas "
            f"→ {stats['caminho']}"
        )
        self.lbl_status_db.setStyleSheet(f"color: {SUCCESS};")

        msg = (
            f"Exportação concluída.\n\n"
            f"Sheets: {stats['sheets']}\n"
            f"Linhas: {stats['linhas']}\n"
            f"Arquivo: {stats['caminho']}\n"
        )
        if stats.get("ignoradas"):
            msg += f"\nIgnoradas (não existem no banco):\n"
            msg += "\n".join(f"  - {n}" for n in stats["ignoradas"])

        box = QMessageBox(self)
        box.setWindowTitle("Exportação concluída")
        box.setText(msg)
        box.setIcon(QMessageBox.Information)
        abrir = box.addButton("Abrir arquivo", QMessageBox.AcceptRole)
        box.addButton("OK", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is abrir:
            self._abrir_arquivo(stats["caminho"])

    def _on_export_erro(self, msg: str):
        self.btn_export.setEnabled(True)
        self.lbl_status_db.setText(f"Erro na exportação — {msg.splitlines()[0]}")
        self.lbl_status_db.setStyleSheet(f"color: {ERROR};")
        QMessageBox.critical(self, "Erro na exportação", msg)

    # =========================================================
    # Exportacao bruta (CSV/XLSX)
    # =========================================================

    def _exportar_raw(self):
        if self._export_raw_worker is not None and self._export_raw_worker.isRunning():
            return

        # Dialogo pergunta onde salvar. Se o usuario escolher um nome terminado
        # em .xlsx, geramos um unico arquivo; caso contrario tratamos como
        # diretorio e geramos um CSV por tabela.
        from datetime import datetime
        default_xlsx = f"semed_raw_{datetime.now():%Y%m%d_%H%M}.xlsx"
        destino, filtro = QFileDialog.getSaveFileName(
            self,
            "Exportar bruto — .xlsx para arquivo unico ou nome de pasta para CSVs",
            default_xlsx,
            "Excel bruto (*.xlsx);;Pasta (CSV por tabela) (*)",
        )
        if not destino:
            return

        p = Path(destino)
        # Heuristica: se filtro selecionou XLSX, forcamos extensao. Caso
        # contrario, se o usuario nao colocou .xlsx, tratamos como diretorio.
        if "xlsx" in filtro.lower():
            if p.suffix.lower() != ".xlsx":
                p = p.with_suffix(".xlsx")
        else:
            # diretorio: remove eventual .xlsx digitado
            if p.suffix.lower() == ".xlsx":
                p = p.with_suffix("")

        self.btn_export_raw.setEnabled(False)
        self.lbl_status_db.setText("Exportando bruto…")
        self.lbl_status_db.setStyleSheet(f"color: {TEXT_MUTED};")

        self._export_raw_worker = ExportRawWorker(p)
        self._export_raw_worker.progresso.connect(self._on_export_raw_prog)
        self._export_raw_worker.concluido.connect(self._on_export_raw_done)
        self._export_raw_worker.erro.connect(self._on_export_raw_erro)
        self._export_raw_worker.start()

    def _on_export_raw_prog(self, i: int, total: int, nome: str):
        self.lbl_status_db.setText(f"Export bruto {i+1}/{total}: {nome}…")

    def _on_export_raw_done(self, stats: dict):
        self.btn_export_raw.setEnabled(True)
        modo = stats.get("modo")
        if modo == "xlsx":
            self.lbl_status_db.setText(
                f"✓ Bruto exportado: {stats['sheets']} abas · "
                f"{stats['linhas']} linhas → {stats['caminho']}"
            )
            alvo = stats["caminho"]
            corpo = (
                f"Exportação bruta concluída.\n\n"
                f"Abas: {stats['sheets']}\n"
                f"Linhas: {stats['linhas']}\n"
                f"Arquivo: {stats['caminho']}\n"
            )
        else:
            self.lbl_status_db.setText(
                f"✓ Bruto exportado: {stats['arquivos']} CSVs · "
                f"{stats['linhas']} linhas → {stats['destino']}"
            )
            alvo = stats["destino"]
            corpo = (
                f"Exportação bruta concluída.\n\n"
                f"Arquivos CSV: {stats['arquivos']}\n"
                f"Linhas: {stats['linhas']}\n"
                f"Diretório: {stats['destino']}\n"
            )
        self.lbl_status_db.setStyleSheet(f"color: {SUCCESS};")
        if stats.get("ignoradas"):
            corpo += "\nTabelas ausentes no banco:\n"
            corpo += "\n".join(f"  - {n}" for n in stats["ignoradas"])

        box = QMessageBox(self)
        box.setWindowTitle("Exportação bruta concluída")
        box.setText(corpo)
        box.setIcon(QMessageBox.Information)
        abrir = box.addButton("Abrir destino", QMessageBox.AcceptRole)
        box.addButton("OK", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is abrir:
            self._abrir_arquivo(alvo)

    def _on_export_raw_erro(self, msg: str):
        self.btn_export_raw.setEnabled(True)
        self.lbl_status_db.setText(
            f"Erro na exportação bruta — {msg.splitlines()[0]}"
        )
        self.lbl_status_db.setStyleSheet(f"color: {ERROR};")
        QMessageBox.critical(self, "Erro na exportação bruta", msg)

    # =========================================================
    # Shutdown limpo
    # =========================================================

    def closeEvent(self, ev):
        """Garante que workers em execucao sejam cancelados antes de sair.

        Sem isso, fechar a janela enquanto o ProcessadorWorker esta rodando
        pode deixar transacoes em aberto e travar o processo.
        """
        try:
            if hasattr(self.upload_page, "stop_worker_blocking"):
                self.upload_page.stop_worker_blocking(timeout_ms=5000)
            for w in (self._export_worker, self._export_raw_worker, self._db_loader):
                if w is not None and w.isRunning():
                    w.requestInterruption()
                    w.wait(3000)
        except Exception:
            pass
        super().closeEvent(ev)

    def _abrir_arquivo(self, caminho: str):
        """Abre o arquivo com o programa padrao do SO."""
        import os
        import sys
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(caminho)
            elif sys.platform == "darwin":
                subprocess.run(["open", caminho])
            else:
                subprocess.run(["xdg-open", caminho])
        except Exception:
            pass

