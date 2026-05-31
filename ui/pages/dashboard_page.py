"""
Dashboard analítico — 5 seções + filtros temporais.

Seção 1 — KPI cards (Total faturas, kWh, R$, R$/kWh, Δ vs período anterior)
Seção 2 — Série histórica por agrupadora (linha)
Seção 3 — Decomposição de custo (stacked bar)
Seção 4 — Comparativo YoY (linha multi-série por ano)
Seção 5 — Alertas e anomalias (lista scrollável com botão "Ver")

Os gráficos das seções 2–4 usam workers do banco (não self.dados).
Os 4 gráficos originais de sessão são mantidos numa seção colapsável no topo
para compatibilidade quando o banco está offline.

Signals:
    unidade_clicada(str)  — chave da instalação clicada no Top unidades
    alertaNavegar(str, str) — ("instalacao"|"agrupadora", chave)
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QThread, QObject
from PySide6.QtGui import QCursor, QColor, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QComboBox, QLineEdit, QPushButton, QToolTip, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QHeaderView,
)

import pyqtgraph as pg

from ui.theme import ACCENT, TEXT_MUTED, SUCCESS, WARNING, ERROR, BG_CARD, TEXT_PRIMARY, BG_HOVER
from ui.widgets.plot_helper import (
    criar_card_plot, limpar, ajustar_y_com_zero, fixar_x_categorico,
    ajustar_x_com_zero, fixar_y_categorico,
)
from ui.widgets.filtros_temporais import FiltrosTemporaisWidget
from ui.workers.aggregators import (
    DashboardAggregatorWorker,
    SerieHistoricaWorker, DecomposicaoWorker, YoYWorker, CoberturaWorker,
)
from ui.workers.anomaly_detector import AnomalyDetectorWorker


def _fmt_brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_num(v):
    return f"{v:,.0f}".replace(",", ".")


def _fmt_kwh(v):
    return f"{_fmt_num(v)} kWh"


# Cores por agrupadora (ciclo fixo)
_CORES_AG = [ACCENT, "#7FAE6E", "#E0B060", "#9B8EC4", "#6EC4D9"]
# Cores para decomposição de custo
_CORES_DECOMP = {
    "energia":       "#D97757",
    "transmissao":   "#7FAE6E",
    "distribuicao":  "#E0B060",
    "enc_setoriais": "#9B8EC4",
    "tributos":      "#6EC4D9",
    "multa_juros":   "#D46A6A",
    "correcao":      "#9C9892",
}

# Nomes legíveis para labels de decomposição
_LABELS_DECOMP = {
    "energia":       "Energia",
    "transmissao":   "Transmissão",
    "distribuicao":  "Distribuição",
    "enc_setoriais": "Enc. Setoriais",
    "tributos":      "Tributos",
    "multa_juros":   "Multa/Juros",
    "correcao":      "Correção Mon.",
}


# =============================================================
# Worker de complementos (módulo-level — não pode ser inner class
# porque o metaclass do PySide6 não processa Signals corretamente
# em classes definidas dentro de funções)
# =============================================================

class _ComplementosWorker(QThread):
    """Carrega lista de complemento_norm distintos do banco."""
    pronto = Signal(object)   # emite list[str]

    def run(self):
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent.parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from db.connection import get_session, testar_conexao
            from sqlalchemy import text
            testar_conexao()
            session = get_session()
            rows = session.execute(text(
                "SELECT DISTINCT complemento_norm FROM fatura_agrupadora "
                "WHERE complemento_norm IS NOT NULL ORDER BY complemento_norm"
            )).fetchall()
            session.close()
            self.pronto.emit([r[0] for r in rows])
        except Exception:
            self.pronto.emit([])


# =============================================================
# KPI card
# =============================================================

class KPICard(QFrame):
    def __init__(self, label: str, accent: bool = False):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        self.lbl = QLabel(label.upper())
        self.lbl.setObjectName("CardLabel")
        lay.addWidget(self.lbl)
        self.val = QLabel("—")
        self.val.setObjectName("CardAccent" if accent else "CardValue")
        lay.addWidget(self.val)

    def set_value(self, texto: str, cor: str | None = None):
        self.val.setText(texto)
        if cor:
            self.val.setStyleSheet(f"color: {cor}; font-size: 22px; font-weight: 600;")
        else:
            self.val.setStyleSheet("")


# =============================================================
# AlertaItem — linha na lista de alertas
# =============================================================

class AlertaItem(QWidget):
    navegar = Signal(str, str)  # (tipo, chave)

    _COR_SEV = {"ERRO": ERROR, "AVISO": WARNING, "INFO": SUCCESS}
    _CHIP_OBJ = {"ERRO": "ChipError", "AVISO": "ChipWarn", "INFO": "ChipOK"}

    def __init__(self, alerta: dict, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)

        sev = alerta.get("severidade", "INFO")
        chip = QLabel(sev)
        chip.setObjectName(self._CHIP_OBJ.get(sev, "ChipOK"))
        chip.setFixedWidth(46)
        lay.addWidget(chip)

        msg = QLabel(alerta.get("mensagem", ""))
        msg.setWordWrap(True)
        msg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(msg, 1)

        tipo_nav = alerta.get("tipo_nav")
        chave_nav = alerta.get("chave_nav")
        if tipo_nav and chave_nav:
            btn = QPushButton("Ver")
            btn.setFixedWidth(46)
            btn.setFixedHeight(24)
            btn.clicked.connect(
                lambda _=False, t=tipo_nav, c=chave_nav: self.navegar.emit(t, c)
            )
            lay.addWidget(btn)


# =============================================================
# Dashboard principal
# =============================================================

class DashboardPage(QWidget):
    unidade_clicada = Signal(str)
    alertaNavegar = Signal(str, str)  # (tipo_nav, chave_nav)

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.dados: list[dict] = []

        # Workers
        self._aggregator: DashboardAggregatorWorker | None = None
        self._serie_worker: SerieHistoricaWorker | None = None
        self._decomp_worker: DecomposicaoWorker | None = None
        self._yoy_worker: YoYWorker | None = None
        self._anomaly_worker: AnomalyDetectorWorker | None = None
        self._cobertura_worker: CoberturaWorker | None = None
        self._kpi_worker = None

        # Complementos disponíveis no banco (carregados do banco)
        self._complementos_banco: list[str] = []

        # Debounces
        self._debounce_refresh = QTimer(self)
        self._debounce_refresh.setSingleShot(True)
        self._debounce_refresh.setInterval(150)
        self._debounce_refresh.timeout.connect(self._refresh_sessao)

        self._debounce_busca = QTimer(self)
        self._debounce_busca.setSingleShot(True)
        self._debounce_busca.setInterval(300)
        self._debounce_busca.timeout.connect(self._refresh_sessao)

        self._debounce_banco = QTimer(self)
        self._debounce_banco.setSingleShot(True)
        self._debounce_banco.setInterval(400)
        self._debounce_banco.timeout.connect(self._refresh_banco)

        # Metadados de hit-test
        self._hit_meta: dict[pg.PlotWidget, dict] = {}

        # Filtros de sessão
        self._filtro_tensao: str | None = None
        self._filtro_bairro: str | None = None

        # Filtros temporais ativos
        self._filtros_temporais: dict = {
            "granularidade": "mensal",
            "inicio": None,
            "fim": None,
            "complementos": [],
        }

        self._build()
        QTimer.singleShot(300, self._carregar_complementos_banco)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        # Cabeçalho
        header = QHBoxLayout()
        left = QVBoxLayout(); left.setSpacing(0)
        t = QLabel("Dashboard de consumo"); t.setObjectName("PageTitle")
        s = QLabel("Análise histórica das agrupadoras armazenadas no banco.")
        s.setObjectName("PageSubtitle")
        left.addWidget(t); left.addWidget(s)
        header.addLayout(left, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("CardLabel")
        self.lbl_status.setStyleSheet(f"color: {TEXT_MUTED};")
        self.lbl_status.setVisible(False)
        header.addWidget(self.lbl_status, 0, Qt.AlignVCenter)
        root.addLayout(header)

        # Filtros temporais (banco)
        self.filtros_temporais = FiltrosTemporaisWidget()
        self.filtros_temporais.filtrosAlterados.connect(self._on_filtros_temporais)
        root.addWidget(self.filtros_temporais)

        # Scroll area para as 5 seções
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        cont = QWidget()
        cont.setObjectName("Page")
        cl = QVBoxLayout(cont)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(16)

        # ---- Seção 1 — KPIs ----
        kpi_lbl = QLabel("Indicadores do período")
        kpi_lbl.setObjectName("SectionTitle")
        cl.addWidget(kpi_lbl)

        kpi_row = QHBoxLayout(); kpi_row.setSpacing(12)
        self.card_faturas  = KPICard("Total faturas")
        self.card_kwh      = KPICard("Total kWh", accent=True)
        self.card_valor    = KPICard("Total R$")
        self.card_rkwh     = KPICard("R$/kWh médio")
        self.card_delta    = KPICard("Δ vs período anterior")
        for c in [self.card_faturas, self.card_kwh, self.card_valor,
                  self.card_rkwh, self.card_delta]:
            kpi_row.addWidget(c, 1)
        cl.addLayout(kpi_row)

        # ---- Seção 2 — Série histórica ----
        serie_lbl = QLabel("Evolução histórica")
        serie_lbl.setObjectName("SectionTitle")
        cl.addWidget(serie_lbl)

        serie_ctrl = QHBoxLayout()
        self.combo_serie_y = QComboBox()
        self.combo_serie_y.addItem("kWh", "kwh")
        self.combo_serie_y.addItem("R$",  "valor")
        self.combo_serie_y.currentIndexChanged.connect(
            lambda _: self._replot_serie()
        )
        serie_ctrl.addWidget(QLabel("Eixo Y:"))
        serie_ctrl.addWidget(self.combo_serie_y)
        serie_ctrl.addStretch()
        cl.addLayout(serie_ctrl)

        self.plot_serie = criar_card_plot("Série histórica", altura=240)
        cl.addWidget(self.plot_serie)
        self._serie_dados: dict = {}  # cache do worker
        for pw_ref in [self.plot_serie.plot]:
            self._hit_meta[pw_ref] = {"items": [], "orientation": "v", "acao": None}
            pw_ref.scene().sigMouseMoved.connect(
                lambda pos, p=pw_ref: self._on_mouse_move(p, pos)
            )

        # ---- Seção 3 — Decomposição ----
        decomp_lbl = QLabel("Decomposição de custo")
        decomp_lbl.setObjectName("SectionTitle")
        cl.addWidget(decomp_lbl)

        self.plot_decomp = criar_card_plot("Custo por componente", altura=220)
        cl.addWidget(self.plot_decomp)
        self._decomp_dados: list = []

        # ---- Seção 4 — YoY ----
        yoy_lbl = QLabel("Comparativo anual (YoY)")
        yoy_lbl.setObjectName("SectionTitle")
        cl.addWidget(yoy_lbl)

        yoy_ctrl = QHBoxLayout()
        self.combo_yoy_comp = QComboBox()
        self.combo_yoy_comp.setMinimumWidth(180)
        self.combo_yoy_comp.currentIndexChanged.connect(
            lambda _: self._disparar_yoy()
        )
        yoy_ctrl.addWidget(QLabel("Agrupadora:"))
        yoy_ctrl.addWidget(self.combo_yoy_comp)
        yoy_ctrl.addStretch()
        cl.addLayout(yoy_ctrl)

        self.plot_yoy = criar_card_plot("R$ por mês × ano", altura=220)
        cl.addWidget(self.plot_yoy)
        self._yoy_dados: dict = {}

        # ---- Seção 5 — Alertas ----
        alertas_lbl = QLabel("Alertas e anomalias")
        alertas_lbl.setObjectName("SectionTitle")
        cl.addWidget(alertas_lbl)

        alertas_ctrl = QHBoxLayout()
        btn_detectar = QPushButton("Detectar anomalias")
        btn_detectar.clicked.connect(self._detectar_anomalias)
        alertas_ctrl.addWidget(btn_detectar)
        self.lbl_alertas_status = QLabel("")
        self.lbl_alertas_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        alertas_ctrl.addWidget(self.lbl_alertas_status, 1)
        cl.addLayout(alertas_ctrl)

        self._alertas_frame = QFrame()
        self._alertas_frame.setObjectName("Card")
        self._alertas_layout = QVBoxLayout(self._alertas_frame)
        self._alertas_layout.setContentsMargins(0, 0, 0, 0)
        self._alertas_layout.setSpacing(0)
        cl.addWidget(self._alertas_frame)

        # ---- Seção 6 — Cobertura histórica ----
        cob_hdr = QHBoxLayout()
        cob_lbl = QLabel("Cobertura histórica")
        cob_lbl.setObjectName("SectionTitle")
        cob_hdr.addWidget(cob_lbl)
        cob_hdr.addStretch()
        self.btn_cobertura = QPushButton("Atualizar cobertura")
        self.btn_cobertura.clicked.connect(self._refresh_cobertura)
        cob_hdr.addWidget(self.btn_cobertura)
        cl.addLayout(cob_hdr)

        self.lbl_cobertura_status = QLabel(
            "Clique em 'Atualizar cobertura' para carregar os dados do banco."
        )
        self.lbl_cobertura_status.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px;"
        )
        cl.addWidget(self.lbl_cobertura_status)

        self._cobertura_scroll = QScrollArea()
        self._cobertura_scroll.setWidgetResizable(True)
        self._cobertura_scroll.setFrameShape(QFrame.NoFrame)
        self._cobertura_scroll.setMaximumHeight(320)
        self._cobertura_table = QTableWidget(0, 0)
        self._cobertura_table.setObjectName("Card")
        self._cobertura_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._cobertura_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._cobertura_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._cobertura_table.setSelectionMode(QTableWidget.NoSelection)
        self._cobertura_scroll.setWidget(self._cobertura_table)
        cl.addWidget(self._cobertura_scroll)

        # ---- Seção "sessão" (gráficos originais) ----
        sessao_lbl = QLabel("Visão da sessão atual")
        sessao_lbl.setObjectName("SectionTitle")
        cl.addWidget(sessao_lbl)

        # Filtros de sessão
        filtros_sess = QHBoxLayout(); filtros_sess.setSpacing(8)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar unidade, bairro, instalação...")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._debounce_busca.start)
        self.busca.setMinimumWidth(200)
        filtros_sess.addWidget(self.busca, 1)

        self.filtro_ag = QComboBox()
        self.filtro_ag.addItem("Todas as agrupadoras", None)
        self.filtro_ag.currentIndexChanged.connect(self._debounce_refresh.start)
        self.filtro_ag.setMinimumWidth(200)
        filtros_sess.addWidget(self.filtro_ag, 0)

        self.filtro_tensao = QComboBox()
        self.filtro_tensao.addItem("Todas as tensões", None)
        self.filtro_tensao.currentIndexChanged.connect(self._on_filtro_tensao_changed)
        self.filtro_tensao.setMinimumWidth(130)
        filtros_sess.addWidget(self.filtro_tensao, 0)

        self.btn_limpar = QPushButton("Limpar filtros")
        self.btn_limpar.clicked.connect(self._limpar_filtros)
        self.btn_limpar.setEnabled(False)
        filtros_sess.addWidget(self.btn_limpar, 0)
        cl.addLayout(filtros_sess)

        cards_row = QHBoxLayout(); cards_row.setSpacing(12)
        self.card_sess_faturas = KPICard("Faturas (sessão)")
        self.card_sess_kwh     = KPICard("kWh (sessão)", accent=True)
        self.card_sess_valor   = KPICard("R$ (sessão)")
        self.card_sess_unid    = KPICard("Unidades (sessão)")
        for c in [self.card_sess_faturas, self.card_sess_kwh,
                  self.card_sess_valor, self.card_sess_unid]:
            cards_row.addWidget(c, 1)
        cl.addLayout(cards_row)

        grid = QGridLayout(); grid.setSpacing(12)
        self.plot_top    = criar_card_plot("Top 10 unidades por valor (R$)", altura=200)
        self.plot_tensao = criar_card_plot("Distribuição por tensão", altura=200)
        self.plot_bairro = criar_card_plot("Top 10 bairros por consumo (kWh)", altura=200)
        self.plot_dist   = criar_card_plot("Distribuição de valores", altura=200)
        grid.addWidget(self.plot_top,    0, 0)
        grid.addWidget(self.plot_tensao, 0, 1)
        grid.addWidget(self.plot_bairro, 1, 0)
        grid.addWidget(self.plot_dist,   1, 1)
        grid.setRowStretch(0, 1); grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
        cl.addLayout(grid)

        for card, acao in (
            (self.plot_top,    self._on_click_unidade),
            (self.plot_tensao, self._on_click_tensao),
            (self.plot_bairro, self._on_click_bairro),
            (self.plot_dist,   None),
        ):
            pw: pg.PlotWidget = card.plot
            self._hit_meta[pw] = {"items": [], "orientation": "v", "acao": acao}
            pw.scene().sigMouseMoved.connect(
                lambda pos, p=pw: self._on_mouse_move(p, pos)
            )
            pw.scene().sigMouseClicked.connect(
                lambda ev, p=pw: self._on_mouse_click(p, ev)
            )
            if acao is not None:
                pw.setCursor(Qt.PointingHandCursor)

        scroll.setWidget(cont)
        root.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    # Seção 6 — Cobertura histórica
    # ------------------------------------------------------------------

    def _refresh_cobertura(self):
        if self._cobertura_worker and self._cobertura_worker.isRunning():
            self._cobertura_worker.cancelar()
            QTimer.singleShot(150, self._refresh_cobertura)
            return

        self.lbl_cobertura_status.setText("Carregando cobertura…")
        self._cobertura_worker = CoberturaWorker()
        self._cobertura_worker.pronto.connect(self._on_cobertura_pronta)
        self._cobertura_worker.start()

    def _on_cobertura_pronta(self, dados: dict):
        complementos = dados.get("complementos", [])
        periodos     = dados.get("periodos", [])
        matriz       = dados.get("dados", {})

        t = self._cobertura_table
        t.clear()

        if not complementos or not periodos:
            self.lbl_cobertura_status.setText("Sem dados de cobertura no banco.")
            t.setRowCount(0)
            t.setColumnCount(0)
            return

        from datetime import date
        hoje = date.today()
        mes_atual = f"{hoje.year:04d}-{hoje.month:02d}"

        t.setRowCount(len(complementos))
        t.setColumnCount(len(periodos))
        t.setVerticalHeaderLabels(complementos)
        t.setHorizontalHeaderLabels(periodos)

        cor_ok    = QColor(SUCCESS + "55")  # verde translúcido
        cor_ok_fg = QColor(SUCCESS)
        cor_vazio = QColor(BG_HOVER)
        cor_muted = QColor(TEXT_MUTED)

        for row, comp in enumerate(complementos):
            for col, periodo in enumerate(periodos):
                if periodo > mes_atual:
                    item = QTableWidgetItem("—")
                    item.setBackground(cor_vazio)
                    item.setForeground(cor_muted)
                    t.setItem(row, col, item)
                    continue

                chave = (comp, periodo)
                if chave in matriz:
                    info = matriz[chave]
                    vt = info["valor_total"]
                    nf = info["n_faturas"]
                    texto = (
                        f"R$ {vt:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        + f"\n({nf})"
                    )
                    item = QTableWidgetItem(texto)
                    item.setBackground(cor_ok)
                    item.setForeground(cor_ok_fg)
                    item.setTextAlignment(Qt.AlignCenter)
                else:
                    item = QTableWidgetItem("—")
                    item.setBackground(cor_vazio)
                    item.setForeground(cor_muted)
                    item.setTextAlignment(Qt.AlignCenter)
                t.setItem(row, col, item)

        n_total = len(complementos) * len(periodos)
        n_preench = len(matriz)
        pct = n_preench / n_total * 100 if n_total else 0
        self.lbl_cobertura_status.setText(
            f"{n_preench}/{n_total} células com dados ({pct:.0f}%)"
        )

    # ------------------------------------------------------------------
    # Carregamento de complementos do banco
    # ------------------------------------------------------------------

    def _carregar_complementos_banco(self):
        self._comp_loader = _ComplementosWorker()
        self._comp_loader.pronto.connect(self._on_complementos_prontos)
        self._comp_loader.start()

    def _on_complementos_prontos(self, complementos: list[str]):
        self._complementos_banco = complementos
        self.filtros_temporais.set_complementos(complementos)
        # Popular combo YoY
        self.combo_yoy_comp.blockSignals(True)
        self.combo_yoy_comp.clear()
        for c in complementos:
            self.combo_yoy_comp.addItem(c, c)
        self.combo_yoy_comp.blockSignals(False)
        # Dispara refresh inicial do banco
        self._debounce_banco.start()

    # ------------------------------------------------------------------
    # Filtros temporais → refresh banco
    # ------------------------------------------------------------------

    def _on_filtros_temporais(self, filtros: dict):
        self._filtros_temporais = filtros
        self._debounce_banco.start()

    def _refresh_banco(self):
        self._refresh_serie()
        self._refresh_decomp()
        self._refresh_kpis_banco()
        self._disparar_yoy()

    # ------------------------------------------------------------------
    # Seção 2 — Série histórica
    # ------------------------------------------------------------------

    def _refresh_serie(self):
        if self._serie_worker and self._serie_worker.isRunning():
            self._serie_worker.cancelar()
            QTimer.singleShot(150, self._refresh_serie)
            return

        ft = self._filtros_temporais
        self._serie_worker = SerieHistoricaWorker(
            complementos=ft["complementos"],
            granularidade=ft["granularidade"],
            inicio=ft["inicio"],
            fim=ft["fim"],
        )
        self._serie_worker.pronto.connect(self._on_serie_pronta)
        self._serie_worker.start()

    def _on_serie_pronta(self, resultado: dict):
        self._serie_dados = resultado.get("series", {})
        self._replot_serie()

    def _replot_serie(self):
        pw = self.plot_serie.plot
        limpar(pw)
        series = self._serie_dados
        if not series:
            self.plot_serie.lbl_empty.setVisible(True)
            return
        self.plot_serie.lbl_empty.setVisible(False)

        eixo_y = self.combo_serie_y.currentData() or "kwh"
        unidade = "kWh" if eixo_y == "kwh" else "R$"

        # Coletar todos os períodos (eixo X categórico unificado)
        todos_periodos: list[str] = sorted({
            p["periodo"]
            for dados in series.values()
            for p in dados
        })
        if not todos_periodos:
            self.plot_serie.lbl_empty.setVisible(True)
            return

        periodo_idx = {p: i for i, p in enumerate(todos_periodos)}
        x_ticks = list(zip(range(len(todos_periodos)), todos_periodos))

        # Legenda criada APÓS limpar() e ANTES dos pw.plot()
        plot_item = pw.getPlotItem()
        legend = plot_item.addLegend(offset=(-10, 10), labelTextSize="8pt")
        legend.setBrush(pg.mkBrush(30, 30, 30, 200))
        legend.setPen(pg.mkPen("#3A3937"))

        meta_items = []
        for idx_comp, (comp, dados) in enumerate(series.items()):
            cor = _CORES_AG[idx_comp % len(_CORES_AG)]
            x_vals = [periodo_idx[d["periodo"]] for d in dados if d["periodo"] in periodo_idx]
            y_vals = [d[eixo_y] for d in dados if d["periodo"] in periodo_idx]
            if not x_vals:
                continue
            nome_curto = (comp[:18] + "…") if len(comp) > 18 else comp
            if len(x_vals) == 1:
                pw.plot(
                    x_vals, y_vals,
                    pen=None, symbol="o", symbolBrush=cor,
                    symbolSize=10, symbolPen=pg.mkPen("#1C1B1A", width=1),
                    name=nome_curto,
                )
            else:
                pw.plot(
                    x_vals, y_vals,
                    pen=pg.mkPen(cor, width=2), symbol="o", symbolBrush=cor,
                    symbolSize=7, symbolPen=pg.mkPen("#1C1B1A", width=1),
                    name=nome_curto,
                )
            for xi, yi in zip(x_vals, y_vals):
                meta_items.append({
                    "label": f"{comp} — {todos_periodos[xi]}",
                    "valor_fmt": (
                        _fmt_kwh(yi) if eixo_y == "kwh" else _fmt_brl(yi)
                    ),
                    "x0": xi - 0.4, "x1": xi + 0.4,
                    "y0": 0.0, "y1": yi,
                    "key": None,
                })

        pw.getAxis("bottom").setTicks([x_ticks])
        pw.setLabel("left", unidade)
        fixar_x_categorico(pw, len(todos_periodos), margem=0.5)
        todos_y = [
            d[eixo_y] for dados in series.values() for d in dados
        ]
        ajustar_y_com_zero(pw, todos_y)
        self._hit_meta[pw] = {"items": meta_items, "orientation": "v", "acao": None}

    # ------------------------------------------------------------------
    # Seção 3 — Decomposição
    # ------------------------------------------------------------------

    def _refresh_decomp(self):
        if self._decomp_worker and self._decomp_worker.isRunning():
            self._decomp_worker.cancelar()
            QTimer.singleShot(150, self._refresh_decomp)
            return

        ft = self._filtros_temporais
        self._decomp_worker = DecomposicaoWorker(
            complementos=ft["complementos"],
            granularidade=ft["granularidade"],
            inicio=ft["inicio"],
            fim=ft["fim"],
        )
        self._decomp_worker.pronto.connect(self._on_decomp_pronta)
        self._decomp_worker.start()

    def _on_decomp_pronta(self, dados: list):
        self._decomp_dados = dados
        self._replot_decomp()

    def _replot_decomp(self):
        pw = self.plot_decomp.plot
        limpar(pw)
        dados = self._decomp_dados
        if not dados:
            self.plot_decomp.lbl_empty.setVisible(True)
            return
        self.plot_decomp.lbl_empty.setVisible(False)

        campos = ["energia", "transmissao", "distribuicao",
                  "enc_setoriais", "tributos", "multa_juros", "correcao"]
        x = list(range(len(dados)))
        periodos = [d["periodo"] for d in dados]

        base = [0.0] * len(dados)
        campos_presentes = []
        for campo in campos:
            vals = [d.get(campo, 0.0) for d in dados]
            if not any(v > 0 for v in vals):
                continue
            campos_presentes.append(campo)
            cor = _CORES_DECOMP[campo]
            pw.addItem(pg.BarGraphItem(
                x=x, y0=base, y1=[b + v for b, v in zip(base, vals)],
                width=0.7, brush=cor, pen=None,
            ))
            base = [b + v for b, v in zip(base, vals)]

        # Legenda manual (BarGraphItem não suporta name=)
        if campos_presentes:
            plot_item = pw.getPlotItem()
            n_cols = 2 if len(campos_presentes) > 3 else 1
            legend = plot_item.addLegend(offset=(-10, 10), labelTextSize="8pt",
                                         colCount=n_cols)
            legend.setBrush(pg.mkBrush(30, 30, 30, 200))
            legend.setPen(pg.mkPen("#3A3937"))
            for campo in campos_presentes:
                sample = pg.PlotDataItem(
                    symbol="s", symbolSize=12,
                    symbolBrush=pg.mkBrush(_CORES_DECOMP[campo]),
                    symbolPen=pg.mkPen(None), pen=None,
                )
                legend.addItem(sample, _LABELS_DECOMP.get(campo, campo))

        pw.getAxis("bottom").setTicks([list(zip(x, periodos))])
        pw.setLabel("left", "R$")
        fixar_x_categorico(pw, len(x))
        ajustar_y_com_zero(pw, base)

    # ------------------------------------------------------------------
    # Seção 4 — YoY
    # ------------------------------------------------------------------

    def _disparar_yoy(self):
        comp = self.combo_yoy_comp.currentData()
        if not comp:
            return

        anos = sorted(self._complementos_banco and [
            ano for ano in range(2020, date.today().year + 1)
        ] or [], reverse=True)[:6]  # últimos 6 anos
        if not anos:
            anos = list(range(date.today().year - 5, date.today().year + 1))

        if self._yoy_worker and self._yoy_worker.isRunning():
            self._yoy_worker.cancelar()
            QTimer.singleShot(150, self._disparar_yoy)
            return

        self._yoy_worker = YoYWorker(comp, anos)
        self._yoy_worker.pronto.connect(self._on_yoy_pronto)
        self._yoy_worker.start()

    def _on_yoy_pronto(self, dados: dict):
        self._yoy_dados = dados
        self._replot_yoy()

    def _replot_yoy(self):
        pw = self.plot_yoy.plot
        limpar(pw)
        dados = self._yoy_dados
        if not dados:
            self.plot_yoy.lbl_empty.setVisible(True)
            return
        self.plot_yoy.lbl_empty.setVisible(False)

        meses_labels = list(zip(
            range(1, 13),
            ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
             "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
        ))

        anos_com_dados = [(ano, serie)
                          for ano, serie in sorted(dados.items(), reverse=True)
                          if serie]
        if not anos_com_dados:
            self.plot_yoy.lbl_empty.setVisible(True)
            return

        # Legenda criada APÓS limpar() e ANTES dos pw.plot()
        plot_item = pw.getPlotItem()
        n_cols = 2 if len(anos_com_dados) > 4 else 1
        legend = plot_item.addLegend(offset=(-10, 10), labelTextSize="8pt",
                                     colCount=n_cols)
        legend.setBrush(pg.mkBrush(30, 30, 30, 200))
        legend.setPen(pg.mkPen("#3A3937"))

        todos_y = []
        for idx_ano, (ano, serie) in enumerate(anos_com_dados):
            cor = _CORES_AG[idx_ano % len(_CORES_AG)]
            x_vals = [d["mes"] for d in serie]
            y_vals = [d["valor"] for d in serie]
            todos_y.extend(y_vals)
            if len(x_vals) == 1:
                pw.plot(
                    x_vals, y_vals,
                    pen=None, symbol="o", symbolBrush=cor,
                    symbolSize=10, symbolPen=pg.mkPen("#1C1B1A", width=1),
                    name=str(ano),
                )
            else:
                pw.plot(
                    x_vals, y_vals,
                    pen=pg.mkPen(cor, width=2), symbol="o", symbolBrush=cor,
                    symbolSize=7, symbolPen=pg.mkPen("#1C1B1A", width=1),
                    name=str(ano),
                )

        pw.getAxis("bottom").setTicks([meses_labels])
        pw.setLabel("left", "R$")
        pw.setXRange(0.5, 12.5, padding=0)
        ajustar_y_com_zero(pw, todos_y)

    # ------------------------------------------------------------------
    # Seção 1 — KPIs do banco
    # ------------------------------------------------------------------

    def _refresh_kpis_banco(self):
        """Calcula KPIs do período filtrado consultando o banco."""
        if self._kpi_worker is not None and self._kpi_worker.isRunning():
            self._kpi_worker.cancelar()
            QTimer.singleShot(150, self._refresh_kpis_banco)
            return

        from PySide6.QtCore import QThread

        class _KpiWorker(QThread):
            from PySide6.QtCore import Signal as _S
            pronto = _S(dict)

            def __init__(self_, ft, ft_anterior):
                super().__init__()
                self_._ft = ft
                self_._ft_ant = ft_anterior

            def run(self_):
                import sys
                from pathlib import Path
                root = Path(__file__).resolve().parent.parent.parent
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                try:
                    from db.connection import get_session, testar_conexao
                    from sqlalchemy import text, bindparam
                    testar_conexao()
                    session = get_session()

                    def _kpis_periodo(ft):
                        filtros = []
                        params = {}
                        if ft.get("complementos"):
                            # `IN :complementos` (expanding) — SQLite e PostgreSQL.
                            filtros.append("fa.complemento_norm IN :complementos")
                            params["complementos"] = ft["complementos"]
                        if ft.get("inicio"):
                            filtros.append(
                                "(fa.ano > :ano_ini OR (fa.ano = :ano_ini AND fa.mes >= :mes_ini))"
                            )
                            params["ano_ini"] = ft["inicio"].year
                            params["mes_ini"] = ft["inicio"].month
                        if ft.get("fim"):
                            filtros.append(
                                "(fa.ano < :ano_fim OR (fa.ano = :ano_fim AND fa.mes <= :mes_fim))"
                            )
                            params["ano_fim"] = ft["fim"].year
                            params["mes_fim"] = ft["fim"].month
                        where = (" AND ".join(filtros)) if filtros else "TRUE"
                        sql = text(f"""
                            SELECT
                                COUNT(fa.id),
                                COALESCE(SUM(fi_agg.total_kwh), 0),
                                COALESCE(SUM(fa.valor_total), 0)
                            FROM fatura_agrupadora fa
                            LEFT JOIN (
                                SELECT agrupadora_id,
                                       SUM(consumo_kwh) AS total_kwh
                                FROM fatura_individual
                                GROUP BY agrupadora_id
                            ) fi_agg ON fi_agg.agrupadora_id = fa.id
                            WHERE {where}
                        """)
                        if ft.get("complementos"):
                            sql = sql.bindparams(bindparam("complementos", expanding=True))
                        row = session.execute(sql, params).fetchone()
                        return row if row else (0, 0, 0)

                    atual = _kpis_periodo(self_._ft)
                    anterior = _kpis_periodo(self_._ft_ant)
                    session.close()

                    n_fat, kwh, valor = int(atual[0]), float(atual[1]), float(atual[2])
                    rkwh = valor / kwh if kwh > 0 else None
                    n_ant, _, val_ant = int(anterior[0]), float(anterior[1]), float(anterior[2])
                    delta = None
                    if val_ant > 0:
                        delta = (valor - val_ant) / val_ant * 100

                    self_.pronto.emit({
                        "n_fat": n_fat, "kwh": kwh, "valor": valor,
                        "rkwh": rkwh, "delta": delta,
                    })
                except Exception:
                    self_.pronto.emit({})

        ft = self._filtros_temporais
        # Período anterior: mesmo intervalo, deslocado para trás
        ft_ant = self._periodo_anterior(ft)
        self._kpi_worker = _KpiWorker(ft, ft_ant)
        self._kpi_worker.pronto.connect(self._on_kpis_banco_prontos)
        self._kpi_worker.start()

    def _periodo_anterior(self, ft: dict) -> dict:
        """Retorna um filtro deslocado para o período imediatamente anterior."""
        inicio = ft.get("inicio")
        fim = ft.get("fim")
        if inicio is None or fim is None:
            return {**ft, "inicio": None, "fim": None}
        delta_dias = (fim - inicio).days + 1
        from datetime import timedelta
        novo_fim = inicio - timedelta(days=1)
        novo_ini = novo_fim - timedelta(days=delta_dias - 1)
        return {**ft, "inicio": novo_ini, "fim": novo_fim}

    def _on_kpis_banco_prontos(self, dados: dict):
        if not dados:
            return
        self.card_faturas.set_value(_fmt_num(dados.get("n_fat", 0)))
        self.card_kwh.set_value(_fmt_kwh(dados.get("kwh", 0)))
        self.card_valor.set_value(_fmt_brl(dados.get("valor", 0)))
        rkwh = dados.get("rkwh")
        self.card_rkwh.set_value(
            f"R$ {rkwh:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if rkwh is not None else "—"
        )
        delta = dados.get("delta")
        if delta is None:
            self.card_delta.set_value("—")
        else:
            sinal = "+" if delta >= 0 else ""
            cor = WARNING if delta >= 0 else SUCCESS
            self.card_delta.set_value(f"{sinal}{delta:.1f}%", cor=cor)

    # ------------------------------------------------------------------
    # Seção 5 — Anomalias
    # ------------------------------------------------------------------

    def _detectar_anomalias(self):
        if self._anomaly_worker and self._anomaly_worker.isRunning():
            self._anomaly_worker.cancelar()
            QTimer.singleShot(150, self._detectar_anomalias)
            return

        # Limpa alertas anteriores
        while self._alertas_layout.count():
            item = self._alertas_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.lbl_alertas_status.setText("Detectando…")
        self._anomaly_worker = AnomalyDetectorWorker()
        self._anomaly_worker.alerta.connect(self._on_alerta)
        self._anomaly_worker.concluido.connect(self._on_deteccao_concluida)
        self._anomaly_worker.start()

    def _on_alerta(self, alerta: dict):
        item = AlertaItem(alerta)
        item.navegar.connect(self._on_alerta_navegar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: #3A3937;")

        if self._alertas_layout.count() > 0:
            self._alertas_layout.addWidget(sep)
        self._alertas_layout.addWidget(item)

    def _on_deteccao_concluida(self):
        n = self._alertas_layout.count() // 2 + (
            1 if self._alertas_layout.count() % 2 == 1 else 0
        )
        self.lbl_alertas_status.setText(
            f"{n} alerta(s) encontrado(s)" if n else "Nenhuma anomalia detectada."
        )

    def _on_alerta_navegar(self, tipo: str, chave: str):
        self.alertaNavegar.emit(tipo, chave)

    # ------------------------------------------------------------------
    # Entrada de dados (sessão)
    # ------------------------------------------------------------------

    def adicionar_item(self, item: dict):
        if "erro" in item:
            return
        self.dados.append(item)
        capa = item.get("capa", {})
        label = f"{capa.get('complemento')} — {capa.get('referencia')}"
        self.filtro_ag.addItem(label, capa.get("documento"))
        tensoes_existentes = {
            self.filtro_tensao.itemData(i)
            for i in range(self.filtro_tensao.count())
        }
        for f in item.get("faturas", []):
            t = f.get("tensao")
            if t and t not in tensoes_existentes:
                self.filtro_tensao.addItem(t, t)
                tensoes_existentes.add(t)
        self._refresh_sessao()

    def _on_filtro_tensao_changed(self):
        self._filtro_tensao = self.filtro_tensao.currentData()
        self._atualizar_estado_limpar()
        self._debounce_refresh.start()

    def _limpar_filtros(self):
        self.busca.clear()
        if self.filtro_ag.count() > 0:
            self.filtro_ag.setCurrentIndex(0)
        if self.filtro_tensao.count() > 0:
            self.filtro_tensao.setCurrentIndex(0)
        self._filtro_tensao = None
        self._filtro_bairro = None
        self._atualizar_estado_limpar()
        self._refresh_sessao()

    def _atualizar_estado_limpar(self):
        ativo = bool(
            self.busca.text().strip()
            or self.filtro_ag.currentIndex() > 0
            or self._filtro_tensao
            or self._filtro_bairro
        )
        self.btn_limpar.setEnabled(ativo)

    def _refresh_sessao(self):
        if self._aggregator is not None and self._aggregator.isRunning():
            self._aggregator.cancelar()
            QTimer.singleShot(150, self._refresh_sessao)
            return

        self.lbl_status.setText("Atualizando…")
        self.lbl_status.setVisible(True)

        doc = self.filtro_ag.currentData()
        self._aggregator = DashboardAggregatorWorker(
            self.dados, doc,
            filtro_tensao=self._filtro_tensao,
            filtro_bairro=getattr(self, "_filtro_bairro", None),
            filtro_texto=self.busca.text(),
        )
        self._aggregator.pronto.connect(self._on_aggregated)
        self._aggregator.start()

    def _on_aggregated(self, resultado: dict):
        kpis = resultado["kpis"]
        self.card_sess_faturas.set_value(_fmt_num(kpis["total_fat"]))
        self.card_sess_kwh.set_value(_fmt_num(kpis["total_kwh"]))
        self.card_sess_valor.set_value(_fmt_brl(kpis["total_valor"]))
        self.card_sess_unid.set_value(_fmt_num(kpis["unidades"]))

        self._plot_top_unidades(resultado["top_unidades"])
        self._plot_tensao(resultado["tensao"])
        self._plot_bairros(resultado["bairros"])
        self._plot_distribuicao(resultado["distribuicao"])

        bairro_filtro = getattr(self, "_filtro_bairro", None)
        if bairro_filtro:
            self.lbl_status.setText(f"Filtrando bairro: {bairro_filtro}")
            self.lbl_status.setVisible(True)
        else:
            self.lbl_status.setVisible(False)

    # ------------------------------------------------------------------
    # Plots de sessão (mantidos do dashboard original)
    # ------------------------------------------------------------------

    def _plot_top_unidades(self, top):
        pw = self.plot_top.plot
        limpar(pw)
        meta_items = []
        if not top:
            self._hit_meta[pw]["items"] = meta_items
            return
        top_norm = [e if len(e) == 3 else (e[0], e[1], "") for e in top]
        nomes = [n for n, _, _ in top_norm]
        valores = [v for _, v, _ in top_norm]
        y = list(range(len(top_norm)))
        pw.addItem(pg.BarGraphItem(
            x0=[0]*len(top_norm), y=y, height=0.7, width=valores,
            brush=ACCENT, pen=None,
        ))
        pw.getAxis("left").setTicks([list(zip(y, nomes))])
        pw.setLabel("bottom", "R$")
        pw.invertY(True)
        fixar_y_categorico(pw, len(y))
        ajustar_x_com_zero(pw, valores)
        for i, (nome, valor, instalacao) in enumerate(top_norm):
            meta_items.append({
                "label": nome, "valor_fmt": _fmt_brl(valor),
                "x0": 0.0, "x1": float(valor),
                "y0": i - 0.35, "y1": i + 0.35,
                "key": instalacao or nome,
            })
        self._hit_meta[pw] = {"items": meta_items, "orientation": "h",
                               "acao": self._on_click_unidade}

    def _plot_tensao(self, itens):
        pw = self.plot_tensao.plot
        limpar(pw)
        meta_items = []
        if not itens:
            self._hit_meta[pw]["items"] = meta_items
            return
        x = list(range(len(itens)))
        nomes = [t for t, _ in itens]
        valores = [c for _, c in itens]
        colors = [ACCENT if t == "B3" else "#7FAE6E" if t == "A4" else "#9C9892"
                  for t in nomes]
        for i, (v, c) in enumerate(zip(valores, colors)):
            pw.addItem(pg.BarGraphItem(x=[i], height=[v], width=0.6, brush=c, pen=None))
        pw.getAxis("bottom").setTicks([list(zip(x, nomes))])
        pw.setLabel("left", "Nº faturas")
        fixar_x_categorico(pw, len(x))
        ajustar_y_com_zero(pw, valores)
        for i, (nome, valor) in enumerate(itens):
            meta_items.append({
                "label": f"Tensão {nome}", "valor_fmt": f"{_fmt_num(valor)} faturas",
                "x0": i - 0.3, "x1": i + 0.3, "y0": 0.0, "y1": float(valor),
                "key": nome,
            })
        self._hit_meta[pw] = {"items": meta_items, "orientation": "v",
                               "acao": self._on_click_tensao}

    def _plot_bairros(self, top):
        pw = self.plot_bairro.plot
        limpar(pw)
        meta_items = []
        if not top:
            self._hit_meta[pw]["items"] = meta_items
            return
        y = list(range(len(top)))
        nomes = [b for b, _ in top]
        valores = [v for _, v in top]
        pw.addItem(pg.BarGraphItem(
            x0=[0]*len(top), y=y, height=0.7, width=valores,
            brush="#7FAE6E", pen=None,
        ))
        pw.getAxis("left").setTicks([list(zip(y, nomes))])
        pw.setLabel("bottom", "kWh")
        pw.invertY(True)
        fixar_y_categorico(pw, len(y))
        ajustar_x_com_zero(pw, valores)
        for i, (nome, valor) in enumerate(top):
            meta_items.append({
                "label": nome, "valor_fmt": _fmt_kwh(valor),
                "x0": 0.0, "x1": float(valor),
                "y0": i - 0.35, "y1": i + 0.35,
                "key": nome,
            })
        self._hit_meta[pw] = {"items": meta_items, "orientation": "h",
                               "acao": self._on_click_bairro}

    def _plot_distribuicao(self, dist):
        pw = self.plot_dist.plot
        limpar(pw)
        meta_items = []
        centers = dist.get("centers") or []
        counts = dist.get("counts") or []
        if not centers or not counts:
            self._hit_meta[pw]["items"] = meta_items
            return
        width = dist["width"]
        mn = dist["min"]; mx = dist["max"]
        pw.addItem(pg.BarGraphItem(
            x=centers, height=counts, width=width*0.85, brush=ACCENT, pen=None
        ))
        pw.setLabel("bottom", "Valor (R$)")
        pw.setLabel("left", "Nº faturas")
        margem = width * 0.6
        pw.setXRange(mn - margem, mx + margem, padding=0)
        ajustar_y_com_zero(pw, counts)
        half = width * 0.85 / 2
        for c, cnt in zip(centers, counts):
            meta_items.append({
                "label": f"{_fmt_brl(c - width/2)} — {_fmt_brl(c + width/2)}",
                "valor_fmt": f"{_fmt_num(cnt)} faturas",
                "x0": c - half, "x1": c + half, "y0": 0.0, "y1": float(cnt),
                "key": None,
            })
        self._hit_meta[pw] = {"items": meta_items, "orientation": "v", "acao": None}

    # ------------------------------------------------------------------
    # Hit-test / tooltip / clique
    # ------------------------------------------------------------------

    def _hit_test(self, pw, scene_pos):
        meta = self._hit_meta.get(pw)
        if not meta or not meta["items"]:
            return None
        vb = pw.getPlotItem().vb
        if vb is None:
            return None
        try:
            view_pt = vb.mapSceneToView(scene_pos)
        except Exception:
            return None
        px, py = view_pt.x(), view_pt.y()
        for it in meta["items"]:
            if it["x0"] <= px <= it["x1"] and it["y0"] <= py <= it["y1"]:
                return it
        return None

    def _on_mouse_move(self, pw, scene_pos):
        hit = self._hit_test(pw, scene_pos)
        if hit is None:
            QToolTip.hideText()
            return
        QToolTip.showText(
            QCursor.pos(),
            f"<b>{hit['label']}</b><br/>{hit['valor_fmt']}",
            pw,
        )

    def _on_mouse_click(self, pw, event):
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit_test(pw, event.scenePos())
        if hit is None:
            return
        meta = self._hit_meta.get(pw) or {}
        acao = meta.get("acao")
        if acao is not None:
            acao(hit["key"])

    def _on_click_unidade(self, nome):
        if nome:
            self.unidade_clicada.emit(nome)

    def _on_click_tensao(self, tensao):
        if not tensao:
            return
        if self._filtro_tensao == tensao:
            idx = 0
        else:
            idx = self.filtro_tensao.findData(tensao)
            if idx < 0:
                return
        self.filtro_tensao.setCurrentIndex(idx)

    def _on_click_bairro(self, bairro):
        if not bairro:
            return
        if getattr(self, "_filtro_bairro", None) == bairro:
            self._filtro_bairro = None
        else:
            self._filtro_bairro = bairro
        self._atualizar_estado_limpar()
        self._debounce_refresh.start()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def clear_all(self):
        self.dados.clear()
        self.filtro_ag.clear()
        self.filtro_ag.addItem("Todas as agrupadoras", None)
        self.filtro_tensao.clear()
        self.filtro_tensao.addItem("Todas as tensões", None)
        self.busca.clear()
        self._filtro_tensao = None
        self._filtro_bairro = None
        self._atualizar_estado_limpar()
        self._refresh_sessao()
