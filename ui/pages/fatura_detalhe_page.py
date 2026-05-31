"""
Pagina de detalhe de uma fatura individual.

Mostra:
- Cabecalho com identificacao (NF, instalacao, unidade)
- Cards com valores-chave
- Tabs: Identificacao | Valores Faturados | Tributos | Valores Medidos
"""
from PySide6.QtCore import Qt, Signal, QSize, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QTableView, QAbstractItemView, QHeaderView, QTabWidget,
)

from ui.theme import ACCENT, TEXT_PRIMARY, TEXT_MUTED
from ui.widgets.icons import lucide_icon


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


# =============================================================
# Modelo de tabela generico
# =============================================================

class DictTableModel(QAbstractTableModel):
    def __init__(self, cols: list[tuple]):
        """cols: [(key, label, formatter, align_right)]"""
        super().__init__()
        self.cols = cols
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
            if v is None:
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
# Cards de cabecalho
# =============================================================

class InfoCard(QFrame):
    def __init__(self, label: str, value: str = "—", accent: bool = False):
        super().__init__()
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        self.lbl = QLabel(label.upper())
        self.lbl.setObjectName("CardLabel")
        self.val = QLabel(value)
        self.val.setObjectName("CardAccent" if accent else "CardValue")
        self.val.setWordWrap(True)
        lay.addWidget(self.lbl)
        lay.addWidget(self.val)

    def set(self, v: str):
        self.val.setText(v)


# =============================================================
# Linha de campo label:valor (para aba identificacao)
# =============================================================

class CampoLinha(QWidget):
    def __init__(self, label: str, value: str = "—"):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        l = QLabel(label)
        l.setStyleSheet(f"color: {TEXT_MUTED}; min-width: 180px;")
        self.v = QLabel(value)
        self.v.setStyleSheet(f"color: {TEXT_PRIMARY};")
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.v.setWordWrap(True)
        lay.addWidget(l, 0)
        lay.addWidget(self.v, 1)

    def set(self, v):
        self.v.setText(str(v) if v is not None and v != "" else "—")


# =============================================================
# Pagina principal
# =============================================================

class FaturaDetalhePage(QWidget):
    voltar = Signal()                  # clique em "Voltar"
    verUnidade = Signal(str)           # clique em "Ver unidade" — envia instalacao

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.fatura: dict | None = None
        self.capa: dict | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        # ---- Header: botao voltar + titulo ----
        header = QHBoxLayout()
        btn_voltar = QPushButton("  Voltar")
        btn_voltar.setIcon(lucide_icon("arrow-left", size=16))
        btn_voltar.setIconSize(QSize(16, 16))
        btn_voltar.setFixedWidth(110)
        btn_voltar.clicked.connect(self.voltar.emit)
        header.addWidget(btn_voltar)
        header.addStretch()
        self.btn_unidade = QPushButton("Ver histórico da unidade  ")
        self.btn_unidade.setIcon(lucide_icon("arrow-right", size=16))
        self.btn_unidade.setIconSize(QSize(16, 16))
        # icone à direita do texto
        self.btn_unidade.setLayoutDirection(Qt.RightToLeft)
        self.btn_unidade.clicked.connect(self._emit_ver_unidade)
        header.addWidget(self.btn_unidade)
        root.addLayout(header)

        t = QLabel("Detalhe da fatura")
        t.setObjectName("PageTitle")
        self.sub = QLabel("Selecione uma fatura na lista de agrupadoras.")
        self.sub.setObjectName("PageSubtitle")
        self.sub.setWordWrap(True)
        root.addWidget(t)
        root.addWidget(self.sub)

        # ---- Cards KPI ----
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_valor = InfoCard("Valor da fatura", accent=True)
        self.card_consumo = InfoCard("Consumo (kWh)")
        self.card_dias = InfoCard("Dias")
        self.card_tensao = InfoCard("Tensão / Classe")
        for c in [self.card_valor, self.card_consumo, self.card_dias, self.card_tensao]:
            cards.addWidget(c, 1)
        root.addLayout(cards)

        # ---- Tabs com dados tabulares ----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_identificacao(), "Identificação")
        self.tabs.addTab(self._tab_valores_fat(), "Valores faturados")
        self.tabs.addTab(self._tab_tributos(), "Tributos")
        self.tabs.addTab(self._tab_valores_med(), "Valores medidos")
        root.addWidget(self.tabs, 1)

    # ---------- Tabs ----------

    def _tab_identificacao(self):
        w = QFrame()
        w.setObjectName("Card")
        g = QGridLayout(w)
        g.setContentsMargins(20, 16, 20, 16)
        g.setHorizontalSpacing(30)
        g.setVerticalSpacing(2)

        self.c_nf = CampoLinha("Nota Fiscal")
        self.c_fatura = CampoLinha("Número da Fatura")
        self.c_inst = CampoLinha("Instalação")
        self.c_uleit = CampoLinha("Unidade de Leitura")
        self.c_conj = CampoLinha("Conjunto/Contrato")
        self.c_nome = CampoLinha("Unidade")
        self.c_end = CampoLinha("Endereço")
        self.c_bairro = CampoLinha("Bairro")
        self.c_mun = CampoLinha("Município")
        self.c_classe_p = CampoLinha("Classe Principal")
        self.c_classe_c = CampoLinha("Classe Consumo")
        self.c_tensao = CampoLinha("Tensão")
        self.c_fase = CampoLinha("Fase")
        self.c_data_fat = CampoLinha("Data do Faturamento")
        self.c_dias = CampoLinha("Dias de Faturamento")
        self.c_leit_ant = CampoLinha("Leitura Anterior")
        self.c_leit_atu = CampoLinha("Leitura Atual")
        self.c_apres = CampoLinha("Apresentação")
        self.c_vecto = CampoLinha("Vencimento")
        self.c_recol = CampoLinha("Recolhimento")
        self.c_hash = CampoLinha("Hash Code")

        col1 = [self.c_nf, self.c_fatura, self.c_inst, self.c_uleit, self.c_conj,
                self.c_nome, self.c_end, self.c_bairro, self.c_mun, self.c_hash]
        col2 = [self.c_classe_p, self.c_classe_c, self.c_tensao, self.c_fase,
                self.c_data_fat, self.c_dias, self.c_leit_ant, self.c_leit_atu,
                self.c_apres, self.c_vecto, self.c_recol]

        for i, widget in enumerate(col1):
            g.addWidget(widget, i, 0)
        for i, widget in enumerate(col2):
            g.addWidget(widget, i, 1)
        return w

    def _tab_valores_fat(self):
        self.tbl_vf = QTableView()
        self.tbl_vf.setAlternatingRowColors(True)
        self.tbl_vf.verticalHeader().setVisible(False)
        self.tbl_vf.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_vf.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl_vf.horizontalHeader().setStretchLastSection(True)
        self.model_vf = DictTableModel([
            ("descricao", "Descrição", None, False),
            ("quantidade", "Quantidade", lambda v: _fmt_num(v, 2), True),
            ("preco", "Preço", lambda v: _fmt_num(v, 6), True),
            ("valor", "Valor", _fmt_brl, True),
        ])
        self.tbl_vf.setModel(self.model_vf)
        return self.tbl_vf

    def _tab_tributos(self):
        self.tbl_tr = QTableView()
        self.tbl_tr.setAlternatingRowColors(True)
        self.tbl_tr.verticalHeader().setVisible(False)
        self.tbl_tr.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl_tr.horizontalHeader().setStretchLastSection(True)
        self.model_tr = DictTableModel([
            ("tipo", "Tipo", None, False),
            ("base_calculo", "Base de Cálculo", _fmt_brl, True),
            ("aliquota", "Alíquota (%)", lambda v: _fmt_num(v, 4), True),
            ("valor", "Valor", _fmt_brl, True),
        ])
        self.tbl_tr.setModel(self.model_tr)
        return self.tbl_tr

    def _tab_valores_med(self):
        self.tbl_vm = QTableView()
        self.tbl_vm.setAlternatingRowColors(True)
        self.tbl_vm.verticalHeader().setVisible(False)
        self.tbl_vm.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl_vm.horizontalHeader().setStretchLastSection(True)
        self.model_vm = DictTableModel([
            ("especie", "Espécie", None, False),
            ("medidor", "Medidor", None, False),
            ("constante", "Cte.", lambda v: _fmt_num(v, 2), True),
            ("perc_fp", "%FP", lambda v: _fmt_num(v, 2), True),
            ("leitura_anterior", "Leitura Anterior", lambda v: _fmt_num(v, 2), True),
            ("leitura_atual", "Leitura Atual", lambda v: _fmt_num(v, 2), True),
            ("medido", "Medido", lambda v: _fmt_num(v, 2), True),
            ("faturado", "Faturado", lambda v: _fmt_num(v, 2), True),
        ])
        self.tbl_vm.setModel(self.model_vm)
        return self.tbl_vm

    # ---------- Plots ----------

    # ---------- API ----------

    def set_fatura(self, fatura: dict, capa: dict | None = None):
        self.fatura = fatura
        self.capa = capa or {}

        grp = self.capa.get("complemento", "")
        ref = self.capa.get("referencia", "")
        self.sub.setText(
            f"Fatura NF {fatura.get('nota_fiscal')} — "
            f"{fatura.get('nome_unidade') or '—'} "
            f"· {grp} {ref}".strip()
        )

        # Cards
        self.card_valor.set(_fmt_brl(fatura.get("valor")))
        self.card_consumo.set(_fmt_num(fatura.get("consumo_kwh"), 2))
        self.card_dias.set(str(fatura.get("dias_faturamento") or "—"))
        tensao = fatura.get("tensao") or "—"
        classe = fatura.get("classe_principal") or "—"
        self.card_tensao.set(f"{tensao} · cl {classe}")

        # Identificacao
        self.c_nf.set(fatura.get("nota_fiscal"))
        self.c_fatura.set(fatura.get("fatura_numero"))
        self.c_inst.set(fatura.get("instalacao"))
        self.c_uleit.set(fatura.get("unidade_leitura"))
        self.c_conj.set(fatura.get("conj_contrato"))
        self.c_nome.set(fatura.get("nome_unidade"))
        self.c_end.set(fatura.get("endereco"))
        self.c_bairro.set(fatura.get("bairro"))
        self.c_mun.set(fatura.get("municipio"))
        self.c_classe_p.set(fatura.get("classe_principal"))
        self.c_classe_c.set(fatura.get("classe_consumo"))
        self.c_tensao.set(fatura.get("tensao"))
        self.c_fase.set(_fmt_num(fatura.get("fase"), 2))
        self.c_data_fat.set(fatura.get("data_faturamento"))
        self.c_dias.set(fatura.get("dias_faturamento"))
        self.c_leit_ant.set(fatura.get("data_leitura_anterior"))
        self.c_leit_atu.set(fatura.get("data_leitura_atual"))
        self.c_apres.set(fatura.get("data_apresentacao"))
        self.c_vecto.set(fatura.get("data_vencimento"))
        self.c_recol.set(fatura.get("data_recolhimento"))
        self.c_hash.set(fatura.get("hash_code"))

        # Tabelas
        self.model_vf.set_rows(fatura.get("valores_faturados", []))
        self.model_tr.set_rows(fatura.get("tributos", []))
        self.model_vm.set_rows(fatura.get("valores_medidos", []))

    def _emit_ver_unidade(self):
        if self.fatura and self.fatura.get("instalacao"):
            self.verUnidade.emit(self.fatura["instalacao"])
