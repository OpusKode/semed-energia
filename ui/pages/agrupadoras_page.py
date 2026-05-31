"""Página de agrupadoras com navegação hierárquica Ano > Mês > Agrupadora.

Layout: QSplitter horizontal em 2 colunas:
  - Esquerda : QTreeWidget Ano > Mês > Agrupadora (contagens do banco)
  - Direita  : QSplitter vertical
      - Topo : tabela de agrupadoras do nó selecionado
      - Base : tabela de faturas individuais da agrupadora selecionada

Campo de busca global no topo: ignora a árvore e usa buscar_global().
API externa mantida: adicionar_item(item), Signal faturaSelecionada.
"""
from __future__ import annotations

from PySide6.QtCore import (
    Qt, Signal, QAbstractTableModel, QModelIndex, QTimer,
    QSortFilterProxyModel, QThread,
)
from PySide6.QtGui import (
    QColor, QAction, QGuiApplication, QPainter, QBrush, QFont,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView,
    QAbstractItemView, QHeaderView, QLineEdit, QSplitter, QFrame,
    QMenu, QTreeWidget, QTreeWidgetItem, QPushButton,
    QStyledItemDelegate, QSizePolicy,
)

from ui.theme import (
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    ACCENT, SUCCESS, WARNING, ERROR,
    BG_CARD, BG_APP, BG_HOVER, BG_SELECTED, BORDER,
)
from ui.workers.aggregators import AgrupadorasFilterWorker
from ui.workers.arvore_loader import ArvoreLoaderWorker

_MESES_PT = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _fmt_brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "-"


def _fmt_kwh(v):
    try:
        if v is None or v == "":
            return "-"
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "-"


# =============================================================
# Delegate de status com chip colorido
# =============================================================

class _StatusDelegate(QStyledItemDelegate):
    """Renderiza chips coloridos inline para a coluna de status."""

    _CHIPS = {
        "ok":       (SUCCESS,  "✓  Ok"),
        "erro":     (ERROR,    "✗  Erro"),
        "warnings": (WARNING,  "⚠  Aviso"),
    }

    def paint(self, painter, option, index):
        text = (index.data(Qt.DisplayRole) or "").strip().lower()
        if text not in self._CHIPS:
            super().paint(painter, option, index)
            return

        fg_hex, label = self._CHIPS[text]
        fg = QColor(fg_hex)
        bg = QColor(fg)
        bg.setAlphaF(0.18)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        r = option.rect.adjusted(8, 5, -8, -5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(r, 8, 8)

        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(fg)
        painter.drawText(r, Qt.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        from PySide6.QtCore import QSize
        return QSize(max(s.width(), 100), max(s.height(), 30))


# =============================================================
# Modelo de tabela simples (reutilizado em ambas as tabelas)
# =============================================================

class SimpleTableModel(QAbstractTableModel):
    """Model genérico com suporte a sort numérico via Qt.EditRole."""

    def __init__(self, rows, cols):
        """cols: [(key, label, formatter), ...]"""
        super().__init__()
        self.rows = rows
        self.cols = cols

    def rowCount(self, parent=QModelIndex()): return len(self.rows)
    def columnCount(self, parent=QModelIndex()): return len(self.cols)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.cols[section][1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key, _, fmt = self.cols[index.column()]
        v = row.get(key)
        if role == Qt.DisplayRole:
            return fmt(v) if fmt else (str(v) if v is not None else "-")
        if role == Qt.EditRole:
            return v if v is not None else ""
        if role == Qt.TextAlignmentRole:
            if isinstance(v, (int, float)) and key != "pagina":
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


# =============================================================
# Worker de busca global via banco
# =============================================================

class BancoBuscaWorker(QThread):
    pronto = Signal(object)  # emite list[dict]

    def __init__(self, termo: str):
        super().__init__()
        self._termo = termo
        self._cancelado = False

    def cancelar(self):
        self._cancelado = True

    def run(self):
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        try:
            from db.connection import get_session, testar_conexao
            from db.repository import buscar_global
            testar_conexao()
        except Exception:
            self.pronto.emit([])
            return

        session = get_session()
        try:
            agrupadoras = buscar_global(session, self._termo)
        except Exception:
            agrupadoras = []
        finally:
            session.close()

        if self._cancelado:
            return

        rows = []
        for ag in agrupadoras:
            if self._cancelado:
                break
            if ag.faturas_com_erro and ag.faturas_com_erro > 0:
                status = "erro"
            elif ag.status == "pendente":
                status = "warnings"
            else:
                status = "ok"
            rows.append({
                "complemento":     ag.complemento,
                "referencia":      ag.referencia,
                "documento":       ag.documento,
                "conta_contrato":  ag.conta_contrato,
                "valor_total":     float(ag.valor_total) if ag.valor_total else 0,
                "qtd_esperada":    ag.qtd_faturas_esperada,
                "faturas_extraidas": ag.faturas_importadas or 0,
                "status":          status,
            })

        if not self._cancelado:
            self.pronto.emit(rows)


# =============================================================
# Helpers de UI
# =============================================================

def _card_frame() -> QFrame:
    """Frame com visual de card (fundo + borda + arredondamento)."""
    f = QFrame()
    f.setObjectName("Card")
    return f


def _panel_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


def _muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
    return lbl


def _empty_state(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(
        f"color: {TEXT_MUTED}; font-size: 13px; padding: 40px 20px;"
    )
    lbl.setWordWrap(True)
    return lbl


# =============================================================
# Página principal
# =============================================================

class AgrupadorasPage(QWidget):
    faturaSelecionada = Signal(dict, dict)  # (fatura, capa)

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.dados: list[dict] = []
        self._item_atual: dict | None = None

        # Estado da seleção na árvore
        self._arvore_ano: int | None = None
        self._arvore_mes: int | None = None
        self._arvore_comp: str | None = None
        self._arvore_dados: dict = {}

        # Modo: "arvore" ou "busca"
        self._modo: str = "arvore"

        self._arvore_worker: ArvoreLoaderWorker | None = None
        self._filter_worker: AgrupadorasFilterWorker | None = None
        self._busca_worker: BancoBuscaWorker | None = None

        self._debounce_busca = QTimer(self)
        self._debounce_busca.setSingleShot(True)
        self._debounce_busca.setInterval(300)
        self._debounce_busca.timeout.connect(self._disparar_busca)

        self._debounce_filtro = QTimer(self)
        self._debounce_filtro.setSingleShot(True)
        self._debounce_filtro.setInterval(250)
        self._debounce_filtro.timeout.connect(self._reload_sessao)

        self._build()
        QTimer.singleShot(200, self._carregar_arvore)

    # ------------------------------------------------------------------
    # Construção da UI
    # ------------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(0)

        # ── Cabeçalho ──────────────────────────────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        t = QLabel("Agrupadoras")
        t.setObjectName("PageTitle")
        s = QLabel("Navegue pela hierarquia Ano › Mês › Agrupadora ou use a busca global.")
        s.setObjectName("PageSubtitle")
        s.setContentsMargins(0, 0, 0, 0)
        title_col.addWidget(t)
        title_col.addWidget(s)
        header_row.addLayout(title_col, 1)

        # Botão de recarregar árvore
        self.btn_reload = QPushButton("↺  Recarregar")
        self.btn_reload.setFixedHeight(32)
        self.btn_reload.clicked.connect(self._carregar_arvore)
        self.btn_reload.setToolTip("Recarrega a hierarquia do banco de dados")
        header_row.addWidget(self.btn_reload, 0, Qt.AlignBottom)

        root.addLayout(header_row)
        root.addSpacing(10)

        # ── Barra de estatísticas (oculta até a árvore carregar) ───────
        self.stats_bar = QFrame()
        self.stats_bar.setStyleSheet(
            f"background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 8px;"
        )
        self.stats_bar.setFixedHeight(64)
        stats_lay = QHBoxLayout(self.stats_bar)
        stats_lay.setContentsMargins(12, 8, 12, 8)
        stats_lay.setSpacing(8)

        self._stat_anos  = self._make_stat("—", "Anos")
        self._stat_meses = self._make_stat("—", "Períodos")
        self._stat_ags   = self._make_stat("—", "Agrupadoras")
        self._stat_fat   = self._make_stat("—", "Faturas")
        for widget in (self._stat_anos, self._stat_meses,
                       self._stat_ags, self._stat_fat):
            stats_lay.addWidget(widget, 1)
        stats_lay.addStretch(0)
        self.stats_bar.hide()
        root.addWidget(self.stats_bar)
        root.addSpacing(10)

        # ── Barra de busca ─────────────────────────────────────────────
        busca_row = QHBoxLayout()
        busca_row.setSpacing(8)

        icon_lbl = QLabel("🔍")
        icon_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 14px;")
        busca_row.addWidget(icon_lbl)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText(
            "Busca global: complemento, documento, conta contrato…"
        )
        self.busca.setClearButtonEnabled(True)
        self.busca.setFixedHeight(34)
        self.busca.textChanged.connect(self._on_busca_changed)
        busca_row.addWidget(self.busca, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.lbl_status.setMinimumWidth(180)
        busca_row.addWidget(self.lbl_status, 0)
        root.addLayout(busca_row)
        root.addSpacing(14)

        # ── Splitter horizontal: árvore | coluna direita ──────────────
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(8)

        # ── Coluna esquerda: árvore ─────────────────────────────────────
        arvore_frame = _card_frame()
        arvore_lay = QVBoxLayout(arvore_frame)
        arvore_lay.setContentsMargins(12, 12, 12, 12)
        arvore_lay.setSpacing(8)

        arv_header_frame = QFrame()
        arv_header_frame.setStyleSheet(
            f"QFrame {{ border-left: 3px solid {ACCENT}; "
            f"background: transparent; margin-left: 2px; }}"
        )
        arv_header_inner = QHBoxLayout(arv_header_frame)
        arv_header_inner.setContentsMargins(8, 2, 0, 2)
        arv_header_inner.setSpacing(8)
        self.lbl_arv = QLabel("Hierarquia")
        self.lbl_arv.setObjectName("SectionTitle")
        arv_header_inner.addWidget(self.lbl_arv)
        arv_header_inner.addStretch()
        self.lbl_arv_status = _muted_label("Carregando…")
        arv_header_inner.addWidget(self.lbl_arv_status)
        arvore_lay.addWidget(arv_header_frame)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(18)
        self.tree.setAlternatingRowColors(False)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: transparent;
                border: none;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 5px 4px;
                border-radius: 5px;
                color: {TEXT_SECONDARY};
            }}
            QTreeWidget::item:hover {{
                background: {BG_HOVER};
                color: {TEXT_PRIMARY};
            }}
            QTreeWidget::item:selected {{
                background: {BG_SELECTED};
                color: {TEXT_PRIMARY};
                border-left: 3px solid {ACCENT};
            }}
            QTreeWidget::branch {{
                background: transparent;
            }}
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                color: {TEXT_MUTED};
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                color: {TEXT_MUTED};
            }}
        """)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        arvore_lay.addWidget(self.tree, 1)
        self._splitter.addWidget(arvore_frame)

        # ── Coluna direita: splitter vertical (agrupadoras / faturas) ──
        self._right_splitter = QSplitter(Qt.Vertical)
        self._right_splitter.setHandleWidth(8)

        # ── Parte superior: tabela de agrupadoras ───────────────────────
        ag_frame = _card_frame()
        ag_lay = QVBoxLayout(ag_frame)
        ag_lay.setContentsMargins(12, 12, 12, 12)
        ag_lay.setSpacing(8)

        ag_header = QHBoxLayout()
        self.lbl_ag_titulo = _panel_label("Agrupadoras")
        ag_header.addWidget(self.lbl_ag_titulo)
        ag_header.addStretch()
        self.lbl_ag_count = _muted_label("")
        ag_header.addWidget(self.lbl_ag_count)
        ag_lay.addLayout(ag_header)

        # Estado vazio (mostrado quando não há dados)
        self.empty_ag = _empty_state("← Selecione um período ou agrupadora na hierarquia")
        ag_lay.addWidget(self.empty_ag)

        self.tbl_ag = QTableView()
        self.tbl_ag.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_ag.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_ag.setAlternatingRowColors(True)
        self.tbl_ag.setSortingEnabled(True)
        self.tbl_ag.verticalHeader().setVisible(False)
        self.tbl_ag.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl_ag.horizontalHeader().setStretchLastSection(True)
        self.tbl_ag.hide()

        cols_ag = [
            ("complemento",      "Grupo",          None),
            ("referencia",       "Referência",      None),
            ("documento",        "Documento",       None),
            ("conta_contrato",   "Conta Contrato",  None),
            ("valor_total",      "Valor Total",     _fmt_brl),
            ("qtd_esperada",     "Faturas",         None),
            ("faturas_extraidas","Extraídas",        None),
            ("status",           "Status",          None),
        ]
        self.model_ag = SimpleTableModel([], cols_ag)
        self.proxy_ag = QSortFilterProxyModel(self)
        self.proxy_ag.setSourceModel(self.model_ag)
        self.proxy_ag.setSortRole(Qt.EditRole)
        self.tbl_ag.setModel(self.proxy_ag)

        # Delegate de status na última coluna
        self._status_delegate = _StatusDelegate(self.tbl_ag)
        status_col_idx = next(
            i for i, c in enumerate(cols_ag) if c[0] == "status"
        )
        self.tbl_ag.setItemDelegateForColumn(status_col_idx, self._status_delegate)

        self.tbl_ag.selectionModel().currentRowChanged.connect(self._on_select_ag)
        ag_lay.addWidget(self.tbl_ag, 1)
        self._right_splitter.addWidget(ag_frame)

        # ── Parte inferior: faturas individuais ─────────────────────────
        fat_frame = _card_frame()
        fat_lay = QVBoxLayout(fat_frame)
        fat_lay.setContentsMargins(12, 12, 12, 12)
        fat_lay.setSpacing(8)

        fat_header = QHBoxLayout()
        self.lbl_fat = _panel_label("Faturas individuais")
        fat_header.addWidget(self.lbl_fat)
        fat_header.addStretch()
        self.lbl_fat_count = _muted_label("")
        fat_header.addWidget(self.lbl_fat_count)
        hint = _muted_label("duplo-clique · botão dir.")
        fat_header.addWidget(hint)
        fat_lay.addLayout(fat_header)

        self.empty_fat = _empty_state("← Selecione uma agrupadora para ver as faturas individuais")
        fat_lay.addWidget(self.empty_fat)

        self.tbl_fat = QTableView()
        self.tbl_fat.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_fat.setAlternatingRowColors(True)
        self.tbl_fat.setSortingEnabled(True)
        self.tbl_fat.verticalHeader().setVisible(False)
        self.tbl_fat.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl_fat.horizontalHeader().setStretchLastSection(True)
        self.tbl_fat.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_fat.customContextMenuRequested.connect(self._menu_fatura)
        self.tbl_fat.hide()

        cols_fat = [
            ("nota_fiscal",  "Nota Fiscal",  None),
            ("instalacao",   "Instalação",   None),
            ("nome_unidade", "Unidade",      None),
            ("bairro",       "Bairro",       None),
            ("tensao",       "Tensão",       None),
            ("consumo_kwh",  "kWh",          _fmt_kwh),
            ("dias",         "Dias",         None),
            ("valor",        "Valor",        _fmt_brl),
        ]
        self.model_fat = SimpleTableModel([], cols_fat)
        self.proxy_fat = QSortFilterProxyModel(self)
        self.proxy_fat.setSourceModel(self.model_fat)
        self.proxy_fat.setSortRole(Qt.EditRole)
        self.tbl_fat.setModel(self.proxy_fat)
        self.tbl_fat.doubleClicked.connect(self._abrir_detalhe)
        fat_lay.addWidget(self.tbl_fat, 1)

        self._right_splitter.addWidget(fat_frame)
        self._right_splitter.setSizes([550, 450])

        self._splitter.addWidget(self._right_splitter)
        self._splitter.setSizes([210, 800])

        root.addWidget(self._splitter, 1)

    # ------------------------------------------------------------------
    # Widget de estatística individual
    # ------------------------------------------------------------------

    def _make_stat(self, value: str, label: str) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            f"QFrame {{ background: {BG_APP}; border: 1px solid {BORDER};"
            f" border-radius: 6px; }}"
        )
        col = QVBoxLayout(w)
        col.setContentsMargins(14, 8, 14, 8)
        col.setSpacing(2)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 600;"
            f" border: none; background: transparent;"
        )
        lbl_lbl = QLabel(label)
        lbl_lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px;"
            f" border: none; background: transparent;"
        )
        col.addWidget(lbl_val)
        col.addWidget(lbl_lbl)

        w._val_label = lbl_val  # type: ignore[attr-defined]
        return w

    def _update_stat(self, stat_widget: QWidget, value: str):
        stat_widget._val_label.setText(value)  # type: ignore[attr-defined]

    def _limpar_tabela_fat(self):
        """Limpa a tabela de faturas e reseta o item selecionado."""
        self._item_atual = None
        self.model_fat.set_rows([])
        self.tbl_fat.hide()
        self.empty_fat.show()
        self.lbl_fat.setText("Faturas individuais")
        self.lbl_fat_count.setText("")

    # ------------------------------------------------------------------
    # Carregamento da árvore do banco
    # ------------------------------------------------------------------

    def _carregar_arvore(self):
        if self._arvore_worker is not None and self._arvore_worker.isRunning():
            self._arvore_worker.cancelar()
            QTimer.singleShot(150, self._carregar_arvore)
            return

        self.lbl_arv_status.setText("Carregando…")
        self.btn_reload.setEnabled(False)
        self._arvore_worker = ArvoreLoaderWorker()
        self._arvore_worker.pronto.connect(self._on_arvore_pronta)
        self._arvore_worker.erro.connect(self._on_arvore_erro)
        self._arvore_worker.start()

    def _on_arvore_pronta(self, hierarquia: dict):
        self._arvore_dados = hierarquia
        self._montar_tree_widget(hierarquia)
        self.btn_reload.setEnabled(True)

        # Calcular e exibir estatísticas
        n_anos = len(hierarquia)
        n_meses = sum(len(meses) for meses in hierarquia.values())
        n_ags = sum(
            len(ags)
            for meses in hierarquia.values()
            for ags in meses.values()
        )
        n_fat = sum(
            ag["n_faturas"]
            for meses in hierarquia.values()
            for ags in meses.values()
            for ag in ags
        )
        self._update_stat(self._stat_anos,  str(n_anos))
        self._update_stat(self._stat_meses, str(n_meses))
        self._update_stat(self._stat_ags,   str(n_ags))
        self._update_stat(self._stat_fat,   f"{n_fat:,}".replace(",", "."))
        self.stats_bar.show()
        self.lbl_arv_status.setText(f"{n_anos} ano(s)")

    def _on_arvore_erro(self, msg: str):
        self._set_status(f"Banco offline — {msg.splitlines()[0]}", TEXT_MUTED)
        self.lbl_arv_status.setText("Offline")
        self.btn_reload.setEnabled(True)

    def _montar_tree_widget(self, hierarquia: dict):
        self.tree.blockSignals(True)
        self.tree.clear()

        font_ano = QFont()
        font_ano.setPointSize(12)
        font_ano.setBold(True)

        font_mes = QFont()
        font_mes.setPointSize(11)
        font_mes.setBold(False)

        font_ag = QFont()
        font_ag.setPointSize(10)

        first_item = None
        for i, ano in enumerate(sorted(hierarquia.keys(), reverse=True)):
            meses = hierarquia[ano]
            total_ano = sum(
                ag["n_faturas"]
                for mes_ags in meses.values()
                for ag in mes_ags
            )
            item_ano = QTreeWidgetItem([f"{ano}   ({total_ano} faturas)"])
            item_ano.setData(0, Qt.UserRole, ("ano", ano, None))
            item_ano.setForeground(0, QColor(TEXT_PRIMARY))
            item_ano.setFont(0, font_ano)

            for mes in sorted(meses.keys()):
                ags = meses[mes]
                total_mes = sum(a["n_faturas"] for a in ags)
                nome_mes = _MESES_PT[mes] if 1 <= mes <= 12 else str(mes)
                item_mes = QTreeWidgetItem([f"{nome_mes}  ({total_mes})"])
                item_mes.setData(0, Qt.UserRole, ("mes", ano, mes))
                item_mes.setForeground(0, QColor(TEXT_SECONDARY))
                item_mes.setFont(0, font_mes)

                for ag in sorted(ags, key=lambda x: x["complemento_norm"]):
                    label = f"{ag['complemento_norm']}  ({ag['n_faturas']})"
                    item_ag = QTreeWidgetItem([label])
                    item_ag.setData(
                        0, Qt.UserRole,
                        ("agrupadora", ano, mes,
                         ag["complemento_norm"], ag["documento"]),
                    )
                    item_ag.setForeground(0, QColor(TEXT_MUTED))
                    item_ag.setFont(0, font_ag)
                    item_mes.addChild(item_ag)

                item_ano.addChild(item_mes)

            self.tree.addTopLevelItem(item_ano)
            # Expande automaticamente o primeiro ano (mais recente)
            if i == 0:
                item_ano.setExpanded(True)
                first_item = item_ano

        self.tree.blockSignals(False)

    # ------------------------------------------------------------------
    # Seleção na árvore
    # ------------------------------------------------------------------

    def _on_tree_selection(self):
        if self._modo == "busca":
            return
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.UserRole)
        if data is None:
            return

        tipo = data[0]
        if tipo == "ano":
            _, ano, _ = data
            self._arvore_ano = ano
            self._arvore_mes = None
            self._arvore_comp = None
            self.lbl_ag_titulo.setText(f"Agrupadoras — {ano}")
        elif tipo == "mes":
            _, ano, mes = data
            self._arvore_ano = ano
            self._arvore_mes = mes
            self._arvore_comp = None
            nome_mes = _MESES_PT[mes] if 1 <= mes <= 12 else str(mes)
            self.lbl_ag_titulo.setText(f"Agrupadoras — {nome_mes}/{ano}")
        elif tipo == "agrupadora":
            _, ano, mes, comp, doc = data
            self._arvore_ano = ano
            self._arvore_mes = mes
            self._arvore_comp = comp
            nome_mes = _MESES_PT[mes] if 1 <= mes <= 12 else str(mes)
            self.lbl_ag_titulo.setText(f"{comp} — {nome_mes}/{ano}")

        self._atualizar_tabela_ag_da_arvore()

    def _atualizar_tabela_ag_da_arvore(self):
        self._limpar_tabela_fat()

        ano  = self._arvore_ano
        mes  = self._arvore_mes
        comp = self._arvore_comp

        rows_sessao = self._rows_sessao(ano, mes, comp)
        rows_banco  = self._rows_banco(ano, mes, comp)

        docs_sessao = {r["documento"] for r in rows_sessao}
        merged = rows_sessao + [r for r in rows_banco if r["documento"] not in docs_sessao]

        self.model_ag.set_rows(merged)
        self._show_ag_table(merged)

    def _show_ag_table(self, rows: list):
        if rows:
            self.empty_ag.hide()
            self.tbl_ag.show()
            self.lbl_ag_count.setText(f"{len(rows)} agrupadora(s)")
        else:
            self.tbl_ag.hide()
            self.empty_ag.show()
            self.lbl_ag_count.setText("")
        self._set_status(f"{len(rows)} agrupadora(s)", TEXT_MUTED)

    def _rows_sessao(self, ano, mes, comp) -> list[dict]:
        rows = []
        for it in self.dados:
            capa = it.get("capa", {})
            ref = capa.get("referencia") or ""
            partes = ref.split("/")
            it_ano = int(partes[1]) if len(partes) == 2 else None
            it_mes = int(partes[0]) if len(partes) == 2 else None
            it_comp = capa.get("complemento") or ""

            if ano is not None and it_ano != ano:
                continue
            if mes is not None and it_mes != mes:
                continue
            if comp is not None and not it_comp.startswith(comp.replace("SEMED-", "SEMED")):
                import re
                _comp_re = re.compile(
                    r"SEMED[\s\-]*" + comp.split("-")[-1] + r"\s*$",
                    re.IGNORECASE,
                )
                if not _comp_re.search(it_comp):
                    continue

            vs = it.get("validacao", {})
            status = "erro" if vs.get("erro", 0) > 0 else (
                "warnings" if vs.get("warn", 0) > 0 else "ok"
            )
            rows.append({
                **capa,
                "faturas_extraidas": it.get("faturas_extraidas"),
                "status": status,
            })
        return rows

    def _rows_banco(self, ano, mes, comp) -> list[dict]:
        hierarquia = self._arvore_dados
        if not hierarquia:
            return []

        anos = [ano] if ano is not None else list(hierarquia.keys())
        rows = []
        for a in anos:
            meses_dados = hierarquia.get(a, {})
            meses_iter = [mes] if mes is not None else list(meses_dados.keys())
            for m in meses_iter:
                ags = meses_dados.get(m, [])
                for ag in ags:
                    if comp is not None and ag["complemento_norm"] != comp:
                        continue
                    rows.append({
                        "complemento":       ag["complemento_norm"],
                        "referencia":        f"{m:02d}/{a}",
                        "documento":         ag["documento"],
                        "conta_contrato":    "",
                        "valor_total":       ag["valor_total"],
                        "qtd_esperada":      None,
                        "faturas_extraidas": ag["n_faturas"],
                        "status":            "ok",
                    })
        return rows

    # ------------------------------------------------------------------
    # Busca global
    # ------------------------------------------------------------------

    def _on_busca_changed(self, texto: str):
        if texto.strip():
            self._modo = "busca"
            self._debounce_busca.start()
        else:
            self._modo = "arvore"
            self.lbl_ag_titulo.setText("Agrupadoras")
            self._atualizar_tabela_ag_da_arvore()
            self.model_fat.set_rows([])
            self.tbl_fat.hide()
            self.empty_fat.show()
            self.lbl_fat.setText("Faturas individuais")
            self.lbl_fat_count.setText("")

    def _disparar_busca(self):
        termo = self.busca.text().strip()
        if not termo:
            return

        if self._busca_worker is not None and self._busca_worker.isRunning():
            self._busca_worker.cancelar()
            QTimer.singleShot(150, self._disparar_busca)
            return

        self._set_status("Buscando…", TEXT_MUTED)
        self.lbl_ag_titulo.setText(f"Resultados — \u201c{termo}\u201d")
        self._busca_worker = BancoBuscaWorker(termo)
        self._busca_worker.pronto.connect(self._on_busca_pronta)
        self._busca_worker.start()

    def _on_busca_pronta(self, rows: list):
        self._limpar_tabela_fat()
        self.model_ag.set_rows(rows)
        self._show_ag_table(rows)
        n = len(rows)
        self._set_status(
            f"{n} resultado(s) para \"{self.busca.text().strip()}\"",
            TEXT_MUTED,
        )

    # ------------------------------------------------------------------
    # Entrada de dados (novos PDFs processados)
    # ------------------------------------------------------------------

    def adicionar_item(self, item: dict):
        if "erro" in item:
            return
        self.dados.append(item)
        if self._modo == "arvore":
            self._atualizar_tabela_ag_da_arvore()
        self._debounce_filtro.start()

    def _reload_sessao(self):
        self._carregar_arvore()

    # ------------------------------------------------------------------
    # Selecao na tabela de agrupadoras
    # ------------------------------------------------------------------

    def _on_select_ag(self, current, previous):
        if not current.isValid():
            return
        src_idx = self.proxy_ag.mapToSource(current)
        rows_visiveis = self.model_ag.rows
        if src_idx.row() >= len(rows_visiveis):
            return
        doc = rows_visiveis[src_idx.row()].get("documento")

        item = next(
            (it for it in self.dados if it.get("capa", {}).get("documento") == doc),
            None,
        )
        self._item_atual = item

        if item:
            faturas = item.get("faturas", [])
            self.model_fat.set_rows(faturas)
            n = len(faturas)
            comp = item["capa"].get("complemento", "")
            self.lbl_fat.setText(f"Faturas \u2014 {comp}")
            self.lbl_fat_count.setText(f"{n} fatura(s)")
            if n:
                self.empty_fat.hide()
                self.tbl_fat.show()
            else:
                self.tbl_fat.hide()
                self.empty_fat.show()
        else:
            self.model_fat.set_rows([])
            self.tbl_fat.hide()
            self.empty_fat.show()
            self.lbl_fat.setText("Faturas individuais")
            self.lbl_fat_count.setText("")

    # ------------------------------------------------------------------
    # Detalhe de fatura
    # ------------------------------------------------------------------

    def _abrir_detalhe(self, index):
        if not index.isValid() or not self._item_atual:
            return
        src_idx = self.proxy_fat.mapToSource(index)
        faturas = self._item_atual.get("faturas", [])
        if src_idx.row() >= len(faturas):
            return
        fatura = faturas[src_idx.row()]
        capa = self._item_atual.get("capa", {})
        self.faturaSelecionada.emit(fatura, capa)

    def _menu_fatura(self, pos):
        if not self._item_atual:
            return
        idx = self.tbl_fat.indexAt(pos)
        if not idx.isValid():
            return
        src_idx = self.proxy_fat.mapToSource(idx)
        faturas = self._item_atual.get("faturas", [])
        if src_idx.row() >= len(faturas):
            return
        fatura = faturas[src_idx.row()]

        menu = QMenu(self)
        act_det = QAction("Ver detalhe\u2026", self)
        act_det.triggered.connect(lambda: self._abrir_detalhe(idx))
        menu.addAction(act_det)
        menu.addSeparator()

        def copiar(valor):
            QGuiApplication.clipboard().setText(str(valor or ""))

        for label, chave in [
            ("Copiar Nota Fiscal",     "nota_fiscal"),
            ("Copiar Instalacao",      "instalacao"),
            ("Copiar Nome da unidade", "nome_unidade"),
        ]:
            act = QAction(label, self)
            act.triggered.connect(lambda _=False, k=chave: copiar(fatura.get(k)))
            menu.addAction(act)

        menu.exec(self.tbl_fat.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, texto, cor=TEXT_MUTED):
        self.lbl_status.setText(texto)
        self.lbl_status.setStyleSheet(f"color: {cor}; font-size: 11px;")
