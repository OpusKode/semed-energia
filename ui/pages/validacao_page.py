"""Pagina de validacao — lista warnings e erros por camada/fatura."""
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableView, QAbstractItemView,
    QHeaderView, QComboBox, QFrame,
)

from ui.theme import (
    SUCCESS, WARNING, ERROR, ACCENT, BG_CARD, BORDER, TEXT_PRIMARY, TEXT_MUTED,
)


class ValidacaoModel(QAbstractTableModel):
    cols = [
        ("severidade", "Severidade"),
        ("camada", "Camada"),
        ("grupo", "Grupo"),
        ("nota", "Nota Fiscal"),
        ("tipo", "Tipo"),
        ("mensagem", "Mensagem"),
    ]

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()): return len(self.rows)
    def columnCount(self, parent=QModelIndex()): return len(self.cols)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return self.cols[s][1]

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        r = self.rows[idx.row()]
        key, _ = self.cols[idx.column()]
        v = r.get(key)
        if role == Qt.DisplayRole:
            return str(v) if v is not None else "-"
        if role == Qt.ForegroundRole and key == "severidade":
            color = ERROR if v == "ERRO" else WARNING
            return QColor(color)
        return None

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class ChipResumo(QFrame):
    def __init__(self, label: str, color: str):
        super().__init__()
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 18px; border: none;")
        self.val = QLabel("0")
        self.val.setObjectName("CardValue")
        self.val.setStyleSheet(f"border: none;")
        lbl = QLabel(label)
        lbl.setObjectName("CardLabel")
        lbl.setStyleSheet("border: none;")

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(lbl)
        col.addWidget(self.val)

        lay.addWidget(dot)
        lay.addLayout(col, 1)


class ValidacaoPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.dados: list[dict] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(12)

        t = QLabel("Validação de integridade")
        t.setObjectName("PageTitle")
        s = QLabel("Warnings e erros detectados nas 3 camadas (estrutural, matemática e semântica).")
        s.setObjectName("PageSubtitle")
        root.addWidget(t)
        root.addWidget(s)

        # Chips de resumo
        chips_row = QHBoxLayout()
        chips_row.setSpacing(12)
        self.chip_ok = ChipResumo("Validações OK", SUCCESS)
        self.chip_warn = ChipResumo("Warnings", WARNING)
        self.chip_erro = ChipResumo("Erros", ERROR)
        chips_row.addWidget(self.chip_ok, 1)
        chips_row.addWidget(self.chip_warn, 1)
        chips_row.addWidget(self.chip_erro, 1)
        root.addLayout(chips_row)

        # Filtros
        filt = QHBoxLayout()
        self.filtro_sev = QComboBox()
        self.filtro_sev.addItems(["Todos", "Apenas ERRO", "Apenas WARN"])
        self.filtro_sev.currentIndexChanged.connect(self._reload)
        self.filtro_cam = QComboBox()
        self.filtro_cam.addItems(["Todas as camadas", "Camada 1 (estrutural)",
                                  "Camada 2 (matemática)", "Camada 3 (semântica)"])
        self.filtro_cam.currentIndexChanged.connect(self._reload)
        self.filtro_ag = QComboBox()
        self.filtro_ag.addItem("Todas as agrupadoras", None)
        self.filtro_ag.currentIndexChanged.connect(self._reload)
        filt.addWidget(QLabel("Severidade:"))
        filt.addWidget(self.filtro_sev)
        filt.addSpacing(16)
        filt.addWidget(QLabel("Camada:"))
        filt.addWidget(self.filtro_cam)
        filt.addSpacing(16)
        filt.addWidget(QLabel("Agrupadora:"))
        filt.addWidget(self.filtro_ag, 1)
        root.addLayout(filt)

        # Tabela
        self.tbl = QTableView()
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.model = ValidacaoModel()
        self.tbl.setModel(self.model)
        root.addWidget(self.tbl, 1)

    # ----- API -----

    def adicionar_item(self, item: dict):
        if "erro" in item:
            return
        self.dados.append(item)
        capa = item.get("capa", {})
        self.filtro_ag.addItem(
            f"{capa.get('complemento')} — {capa.get('referencia')}",
            capa.get("documento"),
        )
        self._reload()

    def clear_all(self):
        self.dados.clear()
        self.filtro_ag.clear()
        self.filtro_ag.addItem("Todas as agrupadoras", None)
        self._reload()

    def _reload(self):
        total_ok = total_warn = total_erro = 0
        doc_filtro = self.filtro_ag.currentData()
        sev_filtro = self.filtro_sev.currentIndex()
        cam_filtro = self.filtro_cam.currentIndex()

        rows = []
        for it in self.dados:
            capa = it.get("capa", {})
            if doc_filtro is not None and capa.get("documento") != doc_filtro:
                continue
            vs = it.get("validacao", {})
            total_ok += vs.get("ok", 0)
            total_warn += vs.get("warn", 0)
            total_erro += vs.get("erro", 0)
            grupo = capa.get("complemento") or "-"

            for e in it.get("erros", []):
                if sev_filtro == 2:  # somente WARN
                    continue
                if cam_filtro and e.get("camada") != cam_filtro:
                    continue
                rows.append({
                    "severidade": "ERRO",
                    "camada": e.get("camada"),
                    "grupo": grupo,
                    "nota": "-",
                    "tipo": e.get("tipo"),
                    "mensagem": e.get("mensagem"),
                })

            for w in it.get("warnings", []):
                if sev_filtro == 1:  # somente ERRO
                    continue
                if cam_filtro and w.get("camada") != cam_filtro:
                    continue
                rows.append({
                    "severidade": "WARN",
                    "camada": w.get("camada"),
                    "grupo": grupo,
                    "nota": w.get("nota") or "-",
                    "tipo": w.get("tipo"),
                    "mensagem": w.get("mensagem"),
                })

        self.chip_ok.val.setText(str(total_ok))
        self.chip_warn.val.setText(str(total_warn))
        self.chip_erro.val.setText(str(total_erro))
        self.model.set_rows(rows)
