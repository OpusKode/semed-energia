"""
Página de Unidade Consumidora — enriquecida com dados históricos do banco.

Mantém:
  - adicionar_item(item)     — API de sessão (novos PDFs processados)
  - mostrar_instalacao(str)  — navegar para instalação específica
  - faturaSelecionada signal
  - clear_all()

Adicionado na Fase 4:
  - Combo de instalações populado do banco via InstalacaoLoaderWorker
  - Série temporal via serie_temporal_unidade() (banco) + FiltrosTemporaisWidget
  - Gráfico de sazonalidade (média por mês jan–dez)
  - Linha de tendência linear sobre gráfico de kWh
  - Ranking de consumo médio entre unidades da mesma tensão
  - Botão "Detectar anomalias" → AnomalyDetectorWorker → QDialog
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QSize, Signal, QAbstractTableModel, QModelIndex, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QComboBox, QLineEdit, QTableView, QAbstractItemView, QHeaderView,
    QScrollArea, QToolTip, QPushButton, QDialog, QSizePolicy,
)

import pyqtgraph as pg

from ui.theme import ACCENT, TEXT_PRIMARY, TEXT_MUTED, WARNING, ERROR, SUCCESS
from ui.widgets.plot_helper import (
    criar_card_plot, limpar, ajustar_y_com_zero, fixar_x_categorico,
)
from ui.widgets.filtros_temporais import FiltrosTemporaisWidget
from ui.widgets.icons import lucide_icon
from ui.workers.instalacao_loader import InstalacaoLoaderWorker
from ui.workers.anomaly_detector import AnomalyDetectorWorker


def _fmt_brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "-"


def _fmt_num(v, dec=2):
    try:
        if v is None:
            return "-"
        return f"{float(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "-"


def _ref_to_date(ref: str | None) -> datetime | None:
    if not ref:
        return None
    try:
        m, a = ref.split("/")
        return datetime(int(a), int(m), 1)
    except Exception:
        return None


# =============================================================
# Worker de série temporal do banco
# =============================================================

from PySide6.QtCore import QThread, Signal as _Sig


class _SerieTemporalWorker(QThread):
    pronto = _Sig(list)

    def __init__(self, instalacao: str, granularidade: str, inicio, fim):
        super().__init__()
        self._instalacao = instalacao
        self._granularidade = granularidade
        self._inicio = inicio
        self._fim = fim
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
            from db.repository import serie_temporal_unidade
            testar_conexao()
            session = get_session()
            dados = serie_temporal_unidade(
                session, self._instalacao,
                granularidade=self._granularidade,
                inicio=self._inicio,
                fim=self._fim,
            )
            session.close()
        except Exception:
            dados = []
        if not self._cancelado:
            self.pronto.emit(dados)


class _RankingWorker(QThread):
    pronto = _Sig(dict)  # {"posicao": int, "total": int, "tensao": str}

    def __init__(self, instalacao: str, tensao: str | None):
        super().__init__()
        self._instalacao = instalacao
        self._tensao = tensao
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
            from sqlalchemy import text
            testar_conexao()
            session = get_session()

            tensao_filtro = ""
            params: dict = {"instalacao": self._instalacao}
            if self._tensao:
                tensao_filtro = "AND tensao = :tensao"
                params["tensao"] = self._tensao

            sql = text(f"""
                WITH medias AS (
                    SELECT instalacao, AVG(consumo_kwh) AS media_kwh
                    FROM fatura_individual
                    WHERE consumo_kwh IS NOT NULL AND consumo_kwh > 0
                      {tensao_filtro}
                    GROUP BY instalacao
                )
                SELECT
                    COUNT(*) FILTER (WHERE media_kwh >= (
                        SELECT media_kwh FROM medias WHERE instalacao = :instalacao
                    )) AS posicao,
                    COUNT(*) AS total
                FROM medias
            """)
            row = session.execute(sql, params).fetchone()
            session.close()
            if row:
                self.pronto.emit({
                    "posicao": int(row[0]),
                    "total": int(row[1]),
                    "tensao": self._tensao or "",
                })
            else:
                self.pronto.emit({})
        except Exception:
            self.pronto.emit({})


# =============================================================
# Modelo de tabela
# =============================================================

class FaturasTableModel(QAbstractTableModel):
    cols = [
        ("referencia",      "Referência",      None,                          False),
        ("data_faturamento","Data Fat.",        None,                          False),
        ("dias_faturamento","Dias",             None,                          True),
        ("consumo_kwh",     "Consumo (kWh)",   lambda v: _fmt_num(v, 2),      True),
        ("custo_kwh",       "R$/kWh",          lambda v: _fmt_num(v, 4),      True),
        ("valor",           "Valor",           _fmt_brl,                      True),
        ("nota_fiscal",     "Nota Fiscal",     None,                          False),
        ("tensao",          "Tensão",          None,                          False),
    ]

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []

    def rowCount(self, p=QModelIndex()): return len(self.rows)
    def columnCount(self, p=QModelIndex()): return len(self.cols)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return self.cols[s][1]

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        r = self.rows[idx.row()]
        key, _, fmt, align_right = self.cols[idx.column()]
        v = r.get(key)
        if role == Qt.DisplayRole:
            if v is None or v == "":
                return "-"
            return fmt(v) if fmt else str(v)
        if role == Qt.TextAlignmentRole and align_right:
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


# =============================================================
# Componentes simples
# =============================================================

class InfoCard(QFrame):
    def __init__(self, label: str, accent: bool = False):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        self.lbl = QLabel(label.upper()); self.lbl.setObjectName("CardLabel")
        self.val = QLabel("—")
        self.val.setObjectName("CardAccent" if accent else "CardValue")
        lay.addWidget(self.lbl); lay.addWidget(self.val)

    def set(self, v: str):
        self.val.setText(v)


class CampoLinha(QWidget):
    def __init__(self, label: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        l = QLabel(label); l.setStyleSheet(f"color: {TEXT_MUTED}; min-width: 140px;")
        self.v = QLabel("—")
        self.v.setStyleSheet(f"color: {TEXT_PRIMARY};")
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.v.setWordWrap(True)
        lay.addWidget(l, 0); lay.addWidget(self.v, 1)

    def set(self, v):
        self.v.setText(str(v) if v is not None and v != "" else "—")


# =============================================================
# Dialog de anomalias
# =============================================================

class AnomaliaDialog(QDialog):
    def __init__(self, instalacao: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Anomalias — {instalacao}")
        self.setMinimumSize(600, 400)

        lay = QVBoxLayout(self)

        self.lbl_status = QLabel("Detectando…")
        self.lbl_status.setStyleSheet(f"color: {TEXT_MUTED};")
        lay.addWidget(self.lbl_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._cont = QWidget()
        self._cont_lay = QVBoxLayout(self._cont)
        self._cont_lay.setContentsMargins(0, 0, 0, 0)
        self._cont_lay.setSpacing(0)
        scroll.setWidget(self._cont)
        lay.addWidget(scroll, 1)

        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(self.accept)
        lay.addWidget(btn_fechar, 0, Qt.AlignRight)

        self._n_alertas = 0
        self._worker = AnomalyDetectorWorker(instalacao)
        self._worker.alerta.connect(self._on_alerta)
        self._worker.concluido.connect(self._on_concluido)
        self._worker.start()

    def _on_alerta(self, alerta: dict):
        _SEV_COR = {"ERRO": ERROR, "AVISO": WARNING, "INFO": SUCCESS}
        sev = alerta.get("severidade", "INFO")
        msg = alerta.get("mensagem", "")
        cor = _SEV_COR.get(sev, SUCCESS)

        if self._cont_lay.count() > 0:
            sep = QFrame(); sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #3A3937;")
            self._cont_lay.addWidget(sep)

        row = QHBoxLayout()
        chip = QLabel(sev)
        chip.setFixedWidth(50)
        chip.setStyleSheet(
            f"color: {cor}; font-weight: 600; font-size: 11px;"
        )
        row.addWidget(chip)
        lbl_msg = QLabel(msg); lbl_msg.setWordWrap(True)
        row.addWidget(lbl_msg, 1)
        cont_row = QWidget(); cont_row.setLayout(row)
        self._cont_lay.addWidget(cont_row)
        self._n_alertas += 1

    def _on_concluido(self):
        if self._n_alertas == 0:
            self.lbl_status.setText("Nenhuma anomalia detectada para esta instalação.")
        else:
            self.lbl_status.setText(f"{self._n_alertas} alerta(s) encontrado(s).")

    def closeEvent(self, ev):
        if self._worker.isRunning():
            self._worker.cancelar()
            self._worker.wait(2000)
        super().closeEvent(ev)


# =============================================================
# Página principal
# =============================================================

class UnidadePage(QWidget):
    faturaSelecionada = Signal(dict, dict)

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.por_instalacao: dict[str, dict] = {}
        self._instalacao_atual: str | None = None
        self._plot_meta: dict = {}

        # Workers ativos
        self._serie_worker: _SerieTemporalWorker | None = None
        self._ranking_worker: _RankingWorker | None = None
        self._inst_loader: InstalacaoLoaderWorker | None = None

        # Debounce para filtros temporais
        self._debounce_filtros = QTimer(self)
        self._debounce_filtros.setSingleShot(True)
        self._debounce_filtros.setInterval(350)
        self._debounce_filtros.timeout.connect(self._recarregar_serie)

        self._build()
        QTimer.singleShot(400, self._carregar_instalacoes_banco)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        t = QLabel("Unidade consumidora"); t.setObjectName("PageTitle")
        s = QLabel("Histórico completo de consumo por instalação.")
        s.setObjectName("PageSubtitle")
        root.addWidget(t); root.addWidget(s)

        # Seletor com busca
        sel_row = QHBoxLayout(); sel_row.setSpacing(10)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Pesquisar instalação, unidade, endereço…")
        self.busca.setClearButtonEnabled(True)
        self.busca.addAction(
            lucide_icon("search", color=TEXT_MUTED, size=14),
            QLineEdit.LeadingPosition,
        )
        self.busca.textChanged.connect(self._on_busca)
        self.busca.setMinimumWidth(260)
        sel_row.addWidget(self.busca, 1)

        lbl = QLabel("Instalação:"); lbl.setStyleSheet(f"color: {TEXT_MUTED};")
        sel_row.addWidget(lbl)
        self.combo = QComboBox(); self.combo.setMinimumWidth(380)
        self.combo.currentIndexChanged.connect(self._on_change)
        sel_row.addWidget(self.combo, 2)
        root.addLayout(sel_row)

        self.lbl_resultado = QLabel("")
        self.lbl_resultado.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 11px; padding-bottom: 4px;"
        )
        root.addWidget(self.lbl_resultado)

        # Filtros temporais
        self.filtros = FiltrosTemporaisWidget()
        self.filtros.filtrosAlterados.connect(self._on_filtros_alterados)
        root.addWidget(self.filtros)

        # Scroll area
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        cont = QWidget(); cont.setObjectName("Page")
        cl = QVBoxLayout(cont); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(14)

        # KPI cards
        kpi_row = QHBoxLayout(); kpi_row.setSpacing(10)
        self.card_faturas  = InfoCard("Faturas")
        self.card_kwh_med  = InfoCard("Consumo médio (kWh)", accent=True)
        self.card_val_med  = InfoCard("Valor médio")
        self.card_val_tot  = InfoCard("Valor total pago")
        for c in [self.card_faturas, self.card_kwh_med, self.card_val_med, self.card_val_tot]:
            kpi_row.addWidget(c, 1)
        cl.addLayout(kpi_row)

        # Identificação
        ident = QFrame(); ident.setObjectName("Card")
        il = QGridLayout(ident)
        il.setContentsMargins(20, 14, 20, 14)
        il.setHorizontalSpacing(26); il.setVerticalSpacing(2)

        self.c_inst    = CampoLinha("Instalação")
        self.c_nome    = CampoLinha("Unidade")
        self.c_end     = CampoLinha("Endereço")
        self.c_bairro  = CampoLinha("Bairro")
        self.c_mun     = CampoLinha("Município")
        self.c_uleit   = CampoLinha("Unidade de Leitura")
        self.c_classep = CampoLinha("Classe Principal")
        self.c_classec = CampoLinha("Classe Consumo")
        self.c_tensao  = CampoLinha("Tensão")
        self.c_fase    = CampoLinha("Fase")
        self.c_ranking = CampoLinha("Ranking consumo")

        col1 = [self.c_inst, self.c_nome, self.c_end, self.c_bairro]
        col2 = [self.c_mun, self.c_uleit, self.c_classep, self.c_classec]
        col3 = [self.c_tensao, self.c_fase, self.c_ranking]

        for i, w in enumerate(col1): il.addWidget(w, i, 0)
        for i, w in enumerate(col2): il.addWidget(w, i, 1)
        for i, w in enumerate(col3): il.addWidget(w, i, 2)
        il.setColumnStretch(0, 1); il.setColumnStretch(1, 1); il.setColumnStretch(2, 1)
        cl.addWidget(ident)

        # Gráficos temporais
        graf_title = QLabel("Evolução temporal"); graf_title.setObjectName("SectionTitle")
        cl.addWidget(graf_title)

        self.plot_kwh   = criar_card_plot("Consumo mensal (kWh)", altura=260)
        cl.addWidget(self.plot_kwh)

        graf_grid = QGridLayout(); graf_grid.setSpacing(12)
        self.plot_valor  = criar_card_plot("Valor mensal (R$)", altura=220)
        self.plot_custo  = criar_card_plot("Custo unitário (R$/kWh)", altura=220)
        graf_grid.addWidget(self.plot_valor, 0, 0)
        graf_grid.addWidget(self.plot_custo, 0, 1)
        graf_grid.setColumnStretch(0, 1); graf_grid.setColumnStretch(1, 1)
        cl.addLayout(graf_grid)

        # Sazonalidade
        sazon_lbl = QLabel("Sazonalidade (média por mês)"); sazon_lbl.setObjectName("SectionTitle")
        cl.addWidget(sazon_lbl)
        self.plot_sazon = criar_card_plot("Média histórica por mês", altura=200)
        cl.addWidget(self.plot_sazon)

        # Conectar hover/click em todos os plots
        for card in (self.plot_kwh, self.plot_valor, self.plot_custo, self.plot_sazon):
            pw = card.plot
            self._plot_meta[pw] = []
            pw.scene().sigMouseMoved.connect(
                lambda pos, p=pw: self._on_hover_grafico(p, pos)
            )
            pw.scene().sigMouseClicked.connect(
                lambda ev, p=pw: self._on_click_grafico(p, ev)
            )
            pw.setCursor(Qt.PointingHandCursor)

        # Botão detectar anomalias
        btn_row = QHBoxLayout()
        self.btn_anomalias = QPushButton("Detectar anomalias nesta unidade")
        self.btn_anomalias.clicked.connect(self._detectar_anomalias)
        btn_row.addWidget(self.btn_anomalias)
        btn_row.addStretch()
        cl.addLayout(btn_row)

        # Tabela
        tbl_row = QHBoxLayout()
        tbl_title = QLabel("Faturas armazenadas"); tbl_title.setObjectName("SectionTitle")
        hint = QLabel("(duplo-clique para detalhe)")
        hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        tbl_row.addWidget(tbl_title); tbl_row.addWidget(hint); tbl_row.addStretch()
        cl.addLayout(tbl_row)

        self.tbl = QTableView()
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.model = FaturasTableModel()
        self.tbl.setModel(self.model)
        self.tbl.setMinimumHeight(220)
        self.tbl.doubleClicked.connect(self._abrir_detalhe)
        cl.addWidget(self.tbl)

        scroll.setWidget(cont)
        root.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    # Carregamento de instalações do banco
    # ------------------------------------------------------------------

    def _carregar_instalacoes_banco(self):
        if self._inst_loader and self._inst_loader.isRunning():
            return
        self._inst_loader = InstalacaoLoaderWorker()
        self._inst_loader.pronto.connect(self._on_instalacoes_banco)
        self._inst_loader.start()

    def _on_instalacoes_banco(self, instalacoes: list[dict]):
        for inst in instalacoes:
            chave = inst["instalacao"]
            if chave not in self.por_instalacao:
                self.por_instalacao[chave] = {
                    "unidade": inst["nome_unidade"],
                    "dados": [],
                    "_banco_n": inst["n_faturas"],
                }
        self._refresh_combo()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def adicionar_item(self, item: dict):
        if "erro" in item:
            return
        capa = item.get("capa", {})
        for fat in item.get("faturas", []):
            inst = fat.get("instalacao") or "?"
            fat_enr = dict(fat)
            fat_enr["_capa"] = capa
            kwh = fat.get("consumo_kwh") or 0
            valor = fat.get("valor") or 0
            fat_enr["custo_kwh"] = (valor / kwh) if kwh > 0 else None
            if inst not in self.por_instalacao:
                self.por_instalacao[inst] = {"unidade": fat.get("nome_unidade") or "", "dados": []}
            self.por_instalacao[inst]["dados"].append(fat_enr)
            if not self.por_instalacao[inst].get("unidade"):
                self.por_instalacao[inst]["unidade"] = fat.get("nome_unidade") or ""
        self._refresh_combo()

    def clear_all(self):
        self.por_instalacao.clear()
        self.combo.clear()
        self._limpar()

    def mostrar_instalacao(self, instalacao: str):
        self.busca.blockSignals(True)
        self.busca.clear()
        self.busca.blockSignals(False)
        self._refresh_combo()
        idx = self.combo.findData(instalacao)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Combo + busca
    # ------------------------------------------------------------------

    def _instalacao_bate(self, inst: str, info: dict, termo: str) -> bool:
        if not termo:
            return True
        termo = termo.strip().lower()
        blob = (inst + " " + (info.get("unidade") or "")).lower()
        if info.get("dados"):
            f = info["dados"][-1]
            blob += " " + (f.get("endereco") or "").lower()
            blob += " " + (f.get("bairro") or "").lower()
            blob += " " + (f.get("municipio") or "").lower()
        return termo in blob

    def _on_busca(self, *_):
        self._refresh_combo()

    def _refresh_combo(self):
        atual = self.combo.currentData()
        termo = (self.busca.text() or "").strip()

        self.combo.blockSignals(True)
        self.combo.clear()
        itens_total = sorted(
            self.por_instalacao.items(),
            key=lambda kv: (kv[1].get("unidade") or "", kv[0]),
        )
        itens_filtrados = [
            (inst, info) for inst, info in itens_total
            if self._instalacao_bate(inst, info, termo)
        ]
        for inst, info in itens_filtrados:
            nome = info.get("unidade") or "(sem nome)"
            n_sess = len(info.get("dados") or [])
            n_banco = info.get("_banco_n", 0)
            n = n_sess if n_sess > 0 else n_banco
            self.combo.addItem(f"{inst}  —  {nome}  ({n} faturas)", inst)
        self.combo.blockSignals(False)

        total = len(itens_total)
        vis = len(itens_filtrados)
        if termo:
            self.lbl_resultado.setText(
                f"{vis} de {total} unidades correspondem a \"{termo}\""
            )
        else:
            self.lbl_resultado.setText(f"{total} unidade(s) cadastrada(s)")

        if atual:
            i = self.combo.findData(atual)
            if i >= 0:
                self.combo.setCurrentIndex(i)
                return
        if self.combo.count() > 0:
            self.combo.setCurrentIndex(0)
        else:
            self._limpar()

    def _on_change(self, *_):
        inst = self.combo.currentData()
        if not inst:
            self._limpar()
            return
        self._instalacao_atual = inst
        self._renderizar_metadados(inst)
        self._recarregar_serie()

    # ------------------------------------------------------------------
    # Filtros temporais
    # ------------------------------------------------------------------

    def _on_filtros_alterados(self, filtros: dict):
        self._debounce_filtros.start()
        self._filtros_ativos = filtros

    def _recarregar_serie(self):
        inst = self._instalacao_atual
        if not inst:
            return

        if self._serie_worker and self._serie_worker.isRunning():
            self._serie_worker.cancelar()
            QTimer.singleShot(150, self._recarregar_serie)
            return

        filtros = getattr(self, "_filtros_ativos", {
            "granularidade": "mensal", "inicio": None, "fim": None, "complementos": [],
        })
        self._serie_worker = _SerieTemporalWorker(
            inst,
            granularidade=filtros.get("granularidade", "mensal"),
            inicio=filtros.get("inicio"),
            fim=filtros.get("fim"),
        )
        self._serie_worker.pronto.connect(self._on_serie_pronta)
        self._serie_worker.start()

    def _on_serie_pronta(self, dados: list[dict]):
        """Recebe série do banco [{periodo, kwh, valor, n_faturas}]."""
        if not dados:
            # Fallback para dados de sessão
            inst = self._instalacao_atual
            info = self.por_instalacao.get(inst, {})
            faturas = sorted(
                info.get("dados", []),
                key=lambda f: _ref_to_date(f.get("referencia")) or datetime.min,
            )
            self._renderizar_graficos_sessao(faturas)
            return

        # Renderizar a partir de dados do banco
        self._renderizar_graficos_banco(dados)

    def _renderizar_graficos_banco(self, dados: list[dict]):
        """Plota série temporal vinda do banco (período, kwh, valor)."""
        periodos = [d["periodo"] for d in dados]
        kwh_vals = [d["kwh"] for d in dados]
        val_vals = [d["valor"] for d in dados]
        rkwh_vals = [
            d["valor"] / d["kwh"] if d["kwh"] > 0 else None
            for d in dados
        ]

        x = list(range(len(dados)))

        # Atualiza KPIs
        n = sum(d["n_faturas"] for d in dados)
        total_kwh = sum(kwh_vals)
        total_val = sum(val_vals)
        self.card_faturas.set(str(n))
        self.card_kwh_med.set(_fmt_num(total_kwh / n if n else 0, 2))
        self.card_val_med.set(_fmt_brl(total_val / n if n else 0))
        self.card_val_tot.set(_fmt_brl(total_val))

        # Tabela (sem dados individuais de sessão disponíveis aqui)
        inst = self._instalacao_atual
        info = self.por_instalacao.get(inst, {})
        faturas_sessao = sorted(
            info.get("dados", []),
            key=lambda f: _ref_to_date(f.get("referencia")) or datetime.min,
        )
        if faturas_sessao:
            self.model.set_rows(faturas_sessao)
        else:
            self.model.set_rows([])

        self._plot_linha_banco(self.plot_kwh.plot, x, periodos, kwh_vals, "kWh", ACCENT)
        self._plot_linha_banco(self.plot_valor.plot, x, periodos, val_vals, "R$", "#7FAE6E")
        self._plot_linha_banco(self.plot_custo.plot, x, periodos, rkwh_vals, "R$/kWh", "#E0B060")

        # Sazonalidade
        self._plot_sazonalidade_banco(dados)

        # Tendência no gráfico de kWh
        self._adicionar_tendencia(self.plot_kwh.plot, x, kwh_vals, ACCENT)

    def _plot_linha_banco(self, pw, x, labels, y_raw, unidade, cor):
        limpar(pw); self._plot_meta[pw] = []
        x_v = [xi for xi, yi in zip(x, y_raw) if yi is not None]
        y_v  = [yi for yi in y_raw if yi is not None]
        if not y_v:
            pw.getAxis("bottom").setTicks([list(zip(x, labels))])
            return
        pen = pg.mkPen(cor, width=2)
        pw.plot(x_v, y_v, pen=pen, symbol="o", symbolBrush=cor,
                symbolSize=8, symbolPen=pg.mkPen("#1C1B1A", width=1.5))
        pw.getAxis("bottom").setTicks([list(zip(x, labels))])
        pw.setLabel("left", unidade)
        fixar_x_categorico(pw, len(x), margem=0.5)
        ajustar_y_com_zero(pw, y_v)

        if unidade == "R$":
            fmt_val = _fmt_brl
        elif unidade == "R$/kWh":
            fmt_val = lambda v: _fmt_num(v, 4)
        else:
            fmt_val = lambda v: _fmt_num(v, 2)

        meta = []
        for xi, yi, lbl in zip(x, y_raw, labels):
            if yi is None:
                continue
            meta.append({"x": xi, "y": float(yi), "label": lbl,
                         "valor_fmt": f"{fmt_val(yi)} {unidade}",
                         "fatura_idx": xi})
        self._plot_meta[pw] = meta

    def _plot_sazonalidade_banco(self, dados: list[dict]):
        """Agrupa kWh por mês do ano (1–12) e plota barra de sazonalidade."""
        pw = self.plot_sazon.plot
        limpar(pw); self._plot_meta[pw] = []

        from collections import defaultdict
        soma: dict[int, float] = defaultdict(float)
        cont: dict[int, int] = defaultdict(int)

        for d in dados:
            periodo = d.get("periodo") or ""
            # Extrai mês do período (formatos: "YYYY-MM", "YYYY-TQ", "YYYY-SS", "YYYY")
            partes = periodo.split("-")
            if len(partes) >= 2:
                parte_mes = partes[-1]
                try:
                    if parte_mes.isdigit():
                        mes = int(parte_mes)
                        if 1 <= mes <= 12:
                            soma[mes] += d["kwh"]
                            cont[mes] += 1
                except Exception:
                    pass

        if not soma:
            return

        meses_labels = ["Jan","Fev","Mar","Abr","Mai","Jun",
                        "Jul","Ago","Set","Out","Nov","Dez"]
        x = list(range(1, 13))
        medias = [soma[m] / cont[m] if cont[m] > 0 else 0.0 for m in x]

        pw.addItem(pg.BarGraphItem(
            x=x, height=medias, width=0.7, brush=ACCENT, pen=None
        ))
        pw.getAxis("bottom").setTicks([list(zip(x, meses_labels))])
        pw.setLabel("left", "kWh médio")
        fixar_x_categorico(pw, 12, margem=0.5)
        ajustar_y_com_zero(pw, medias)

    def _adicionar_tendencia(self, pw, x, y_vals, cor_base):
        """Sobrepõe regressão linear simples (mínimos quadrados) ao gráfico."""
        y_clean = [(xi, yi) for xi, yi in zip(x, y_vals) if yi is not None]
        if len(y_clean) < 2:
            return
        xs = [p[0] for p in y_clean]
        ys = [p[1] for p in y_clean]
        n = len(xs)
        sx = sum(xs); sy = sum(ys)
        sxx = sum(xi**2 for xi in xs)
        sxy = sum(xi * yi for xi, yi in zip(xs, ys))
        denom = n * sxx - sx**2
        if denom == 0:
            return
        a = (n * sxy - sx * sy) / denom   # inclinação
        b = (sy - a * sx) / n              # intercepto
        y_trend = [a * xi + b for xi in xs]
        pen_trend = pg.mkPen(cor_base, width=1.5, style=Qt.DashLine)
        pw.plot(xs, y_trend, pen=pen_trend)

        sinal = "↗" if a > 0 else "↘"
        lbl = pg.TextItem(
            text=f"{sinal} y = {a:.2f}x + {b:.1f}",
            color=cor_base, anchor=(1, 0),
        )
        lbl.setPos(xs[-1], y_trend[-1])
        pw.addItem(lbl)

    # ------------------------------------------------------------------
    # Renderização a partir de dados de sessão (fallback)
    # ------------------------------------------------------------------

    def _renderizar_metadados(self, instalacao: str):
        info = self.por_instalacao.get(instalacao, {})
        faturas = sorted(
            info.get("dados", []),
            key=lambda f: _ref_to_date(f.get("referencia")) or datetime.min,
        )
        if not faturas:
            return

        ultima = faturas[-1]
        self.c_inst.set(ultima.get("instalacao"))
        self.c_nome.set(ultima.get("nome_unidade"))
        self.c_end.set(ultima.get("endereco"))
        self.c_bairro.set(ultima.get("bairro"))
        self.c_mun.set(ultima.get("municipio"))
        self.c_classep.set(ultima.get("classe_principal"))
        self.c_classec.set(ultima.get("classe_consumo"))
        self.c_tensao.set(ultima.get("tensao"))
        self.c_fase.set(_fmt_num(ultima.get("fase"), 2))
        self.c_uleit.set(ultima.get("unidade_leitura"))
        self.c_ranking.set("—")

        # Dispara ranking
        tensao = ultima.get("tensao")
        self._disparar_ranking(instalacao, tensao)

    def _disparar_ranking(self, instalacao: str, tensao):
        if self._ranking_worker and self._ranking_worker.isRunning():
            self._ranking_worker.cancelar()
            QTimer.singleShot(150, lambda i=instalacao, t=tensao: self._disparar_ranking(i, t))
            return
        self._ranking_worker = _RankingWorker(instalacao, tensao)
        self._ranking_worker.pronto.connect(self._on_ranking_pronto)
        self._ranking_worker.start()

    def _on_ranking_pronto(self, dado: dict):
        if not dado:
            return
        pos = dado.get("posicao", 0)
        total = dado.get("total", 0)
        tensao = dado.get("tensao", "")
        if total > 0:
            self.c_ranking.set(f"{pos}ª de {total} unidades (tensão {tensao})")

    def _renderizar_graficos_sessao(self, faturas: list[dict]):
        n = len(faturas)
        total_kwh = sum((f.get("consumo_kwh") or 0) for f in faturas)
        total_val = sum((f.get("valor") or 0) for f in faturas)
        self.card_faturas.set(str(n))
        self.card_kwh_med.set(_fmt_num(total_kwh / n if n else 0, 2))
        self.card_val_med.set(_fmt_brl(total_val / n if n else 0))
        self.card_val_tot.set(_fmt_brl(total_val))
        self.model.set_rows(faturas)

        self._plot_linha(self.plot_kwh.plot, faturas, "consumo_kwh", "kWh", ACCENT)
        self._plot_linha(self.plot_valor.plot, faturas, "valor", "R$", "#7FAE6E")
        self._plot_linha(self.plot_custo.plot, faturas, "custo_kwh", "R$/kWh", "#E0B060")

        # Sazonalidade de sessão
        self._plot_sazonalidade_sessao(faturas)

    def _plot_sazonalidade_sessao(self, faturas: list[dict]):
        from collections import defaultdict
        pw = self.plot_sazon.plot
        limpar(pw); self._plot_meta[pw] = []

        soma: dict[int, float] = defaultdict(float)
        cont: dict[int, int] = defaultdict(int)
        for f in faturas:
            ref = f.get("referencia") or ""
            partes = ref.split("/")
            if len(partes) == 2:
                try:
                    mes = int(partes[0])
                    if 1 <= mes <= 12:
                        soma[mes] += f.get("consumo_kwh") or 0
                        cont[mes] += 1
                except Exception:
                    pass

        if not soma:
            return

        meses_lbl = ["Jan","Fev","Mar","Abr","Mai","Jun",
                     "Jul","Ago","Set","Out","Nov","Dez"]
        x = list(range(1, 13))
        medias = [soma[m] / cont[m] if cont[m] > 0 else 0.0 for m in x]
        pw.addItem(pg.BarGraphItem(x=x, height=medias, width=0.7, brush=ACCENT, pen=None))
        pw.getAxis("bottom").setTicks([list(zip(x, meses_lbl))])
        pw.setLabel("left", "kWh médio")
        fixar_x_categorico(pw, 12, margem=0.5)
        ajustar_y_com_zero(pw, medias)

    def _plot_linha(self, pw: pg.PlotWidget, faturas: list[dict],
                    key: str, unidade: str, cor: str):
        limpar(pw); self._plot_meta[pw] = []
        if not faturas:
            return
        x = list(range(len(faturas)))
        labels = [f.get("referencia") or "-" for f in faturas]
        y_raw = [f.get(key) for f in faturas]
        x_v = [xi for xi, yi in zip(x, y_raw) if yi is not None]
        y_v  = [yi for yi in y_raw if yi is not None]
        if not y_v:
            pw.getAxis("bottom").setTicks([list(zip(x, labels))])
            return

        pen = pg.mkPen(cor, width=2)
        pw.plot(x_v, y_v, pen=pen, symbol="o", symbolBrush=cor,
                symbolSize=8, symbolPen=pg.mkPen("#1C1B1A", width=1.5))
        pw.getAxis("bottom").setTicks([list(zip(x, labels))])
        pw.setLabel("left", unidade)
        fixar_x_categorico(pw, len(x), margem=0.5)
        ajustar_y_com_zero(pw, y_v)

        if key == "valor": fmt_val = _fmt_brl
        elif key == "custo_kwh": fmt_val = lambda v: _fmt_num(v, 4)
        else: fmt_val = lambda v: _fmt_num(v, 2)

        meta = []
        for xi, yi, ref, fat in zip(x, y_raw, labels, faturas):
            if yi is None:
                continue
            meta.append({"x": xi, "y": float(yi), "label": ref,
                         "valor_fmt": f"{fmt_val(yi)} {unidade}",
                         "fatura_idx": xi})
        self._plot_meta[pw] = meta

        # Tendência no gráfico de kWh
        if key == "consumo_kwh":
            self._adicionar_tendencia(pw, x_v, y_v, cor)

    # ------------------------------------------------------------------
    # Anomalias
    # ------------------------------------------------------------------

    def _detectar_anomalias(self):
        inst = self._instalacao_atual
        if not inst:
            return
        dlg = AnomaliaDialog(inst, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Hover / click nos pontos dos gráficos
    # ------------------------------------------------------------------

    def _hit_ponto(self, pw, scene_pos):
        pontos = self._plot_meta.get(pw) or []
        if not pontos:
            return None
        vb = pw.getPlotItem().vb
        if vb is None:
            return None
        try:
            view_pt = vb.mapSceneToView(scene_pos)
        except Exception:
            return None
        xr, yr = vb.viewRange()
        tol_x = 0.35
        tol_y = (yr[1] - yr[0]) * 0.10 if yr[1] > yr[0] else 1.0
        melhor = melhor_d = None
        for p in pontos:
            dx = abs(p["x"] - view_pt.x())
            dy = abs(p["y"] - view_pt.y())
            if dx <= tol_x and dy <= tol_y:
                d = (dx / tol_x)**2 + (dy / tol_y)**2
                if melhor is None or d < melhor_d:
                    melhor = p; melhor_d = d
        return melhor

    def _on_hover_grafico(self, pw, scene_pos):
        hit = self._hit_ponto(pw, scene_pos)
        if hit is None:
            QToolTip.hideText()
            return
        QToolTip.showText(QCursor.pos(),
                          f"<b>{hit['label']}</b><br/>{hit['valor_fmt']}", pw)

    def _on_click_grafico(self, pw, event):
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit_ponto(pw, event.scenePos())
        if hit is None:
            return
        faturas = self.model.rows
        idx = hit["fatura_idx"]
        if 0 <= idx < len(faturas):
            fatura = faturas[idx]
            capa = fatura.get("_capa") or {}
            self.faturaSelecionada.emit(fatura, capa)

    # ------------------------------------------------------------------
    # Detalhe de fatura
    # ------------------------------------------------------------------

    def _abrir_detalhe(self, index):
        if not index.isValid() or self._instalacao_atual is None:
            return
        faturas = self.model.rows
        if index.row() >= len(faturas):
            return
        fatura = faturas[index.row()]
        capa = fatura.get("_capa") or {}
        self.faturaSelecionada.emit(fatura, capa)

    # ------------------------------------------------------------------
    # Limpar
    # ------------------------------------------------------------------

    def _limpar(self):
        for c in [self.card_faturas, self.card_kwh_med, self.card_val_med, self.card_val_tot]:
            c.set("—")
        for c in [self.c_inst, self.c_nome, self.c_end, self.c_bairro, self.c_mun,
                  self.c_classep, self.c_classec, self.c_tensao, self.c_fase,
                  self.c_uleit, self.c_ranking]:
            c.set(None)
        for pw in [self.plot_kwh.plot, self.plot_valor.plot,
                   self.plot_custo.plot, self.plot_sazon.plot]:
            limpar(pw)
        self.model.set_rows([])
