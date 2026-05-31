"""Widget reutilizável de filtros temporais para Dashboard e UnidadePage.

Uso básico::

    from ui.widgets.filtros_temporais import FiltrosTemporaisWidget

    w = FiltrosTemporaisWidget()
    w.set_complementos(["SEMED-I", "SEMED-II", "SEMED-III"])
    w.filtrosAlterados.connect(minha_pagina.on_filtros_alterados)
    layout.addWidget(w)

O signal ``filtrosAlterados`` emite um dict com formato::

    {
        "granularidade": "mensal" | "trimestral" | "semestral" | "anual",
        "inicio": datetime.date | None,
        "fim":    datetime.date | None,
        "complementos": list[str],  # [] = todos
    }

Presets de período disponíveis: Últimos 12m, Ano corrente, Ano anterior, Tudo.
Granularidades: Mensal, Trimestral, Semestral, Anual.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QDateEdit, QPushButton, QListWidget, QListWidgetItem,
    QFrame, QSizePolicy,
)

from ui.theme import TEXT_MUTED, ACCENT, BG_CARD, BORDER


class FiltrosTemporaisWidget(QWidget):
    """Barra de filtros temporais reutilizável.

    Signals:
        filtrosAlterados(dict) — emitido ao clicar Aplicar.

    Métodos públicos:
        set_complementos(list[str]) — popula a lista de agrupadoras.
        filtros_atuais() -> dict    — retorna o dict de filtros sem emitir.
        reset()                     — restaura todos os controles ao estado padrão.
    """

    filtrosAlterados = Signal(dict)

    _GRANULARIDADES = ["Mensal", "Trimestral", "Semestral", "Anual"]
    _GRAN_KEYS = ["mensal", "trimestral", "semestral", "anual"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._complementos: list[str] = []
        self._build()
        self._aplicar_preset_ultimos_12m()

    # ------------------------------------------------------------------
    # Construção da UI
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        # Linha 1: granularidade + período + presets
        linha1 = QHBoxLayout()
        linha1.setSpacing(10)

        # Granularidade
        lbl_gran = QLabel("Granularidade:")
        lbl_gran.setStyleSheet(f"color: {TEXT_MUTED};")
        linha1.addWidget(lbl_gran)

        self.combo_gran = QComboBox()
        for g in self._GRANULARIDADES:
            self.combo_gran.addItem(g)
        self.combo_gran.setMinimumWidth(120)
        linha1.addWidget(self.combo_gran)

        linha1.addSpacing(14)

        # Período De/Até
        lbl_de = QLabel("De:")
        lbl_de.setStyleSheet(f"color: {TEXT_MUTED};")
        linha1.addWidget(lbl_de)

        self.date_inicio = QDateEdit()
        self.date_inicio.setCalendarPopup(True)
        self.date_inicio.setDisplayFormat("MM/yyyy")
        self.date_inicio.setMinimumWidth(110)
        linha1.addWidget(self.date_inicio)

        lbl_ate = QLabel("Até:")
        lbl_ate.setStyleSheet(f"color: {TEXT_MUTED};")
        linha1.addWidget(lbl_ate)

        self.date_fim = QDateEdit()
        self.date_fim.setCalendarPopup(True)
        self.date_fim.setDisplayFormat("MM/yyyy")
        self.date_fim.setMinimumWidth(110)
        linha1.addWidget(self.date_fim)

        linha1.addSpacing(10)

        # Presets
        for rotulo, slot in [
            ("Últ. 12m",  self._aplicar_preset_ultimos_12m),
            ("Últ. 24m",  self._aplicar_preset_ultimos_24m),
            ("Ano atual", self._aplicar_preset_ano_corrente),
            ("Ano ant.",  self._aplicar_preset_ano_anterior),
            ("Tudo",      self._aplicar_preset_tudo),
        ]:
            btn = QPushButton(rotulo)
            btn.setFixedHeight(26)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            btn.clicked.connect(slot)
            linha1.addWidget(btn)

        linha1.addStretch()
        outer.addLayout(linha1)

        # Linha 2: agrupadoras + botões Aplicar/Limpar
        linha2 = QHBoxLayout()
        linha2.setSpacing(10)

        lbl_ag = QLabel("Agrupadoras:")
        lbl_ag.setStyleSheet(f"color: {TEXT_MUTED};")
        lbl_ag.setAlignment(Qt.AlignTop)
        linha2.addWidget(lbl_ag)

        self.lista_compl = QListWidget()
        self.lista_compl.setMaximumHeight(72)
        self.lista_compl.setMinimumWidth(200)
        self.lista_compl.setSelectionMode(QListWidget.NoSelection)
        linha2.addWidget(self.lista_compl, 1)

        lbl_hint = QLabel("(nenhuma = todas)")
        lbl_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        lbl_hint.setAlignment(Qt.AlignTop)
        linha2.addWidget(lbl_hint)

        linha2.addStretch()

        btn_aplicar = QPushButton("Aplicar")
        btn_aplicar.setObjectName("Primary")
        btn_aplicar.setFixedHeight(30)
        btn_aplicar.clicked.connect(self._on_aplicar)
        linha2.addWidget(btn_aplicar)

        btn_limpar = QPushButton("Limpar")
        btn_limpar.setFixedHeight(30)
        btn_limpar.clicked.connect(self.reset)
        linha2.addWidget(btn_limpar)

        outer.addLayout(linha2)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def set_complementos(self, complementos: list[str]) -> None:
        """Popula a lista de agrupadoras com checkboxes."""
        self._complementos = list(complementos)
        selecionados = self._complementos_selecionados()
        self.lista_compl.clear()
        for comp in complementos:
            item = QListWidgetItem(comp)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if comp in selecionados else Qt.Unchecked
            )
            self.lista_compl.addItem(item)

    def filtros_atuais(self) -> dict:
        """Retorna o dict de filtros sem emitir o signal."""
        return self._montar_dict()

    def reset(self) -> None:
        """Restaura controles ao estado padrão (últimos 24m, granularidade mensal)."""
        self.combo_gran.setCurrentIndex(0)
        for i in range(self.lista_compl.count()):
            self.lista_compl.item(i).setCheckState(Qt.Unchecked)
        self._aplicar_preset_ultimos_24m()

    # ------------------------------------------------------------------
    # Presets de período
    # ------------------------------------------------------------------

    def _aplicar_preset_ultimos_12m(self) -> None:
        hoje = date.today()
        ini = date(hoje.year - 1, hoje.month, 1)
        self.date_inicio.setDate(QDate(ini.year, ini.month, 1))
        self.date_fim.setDate(QDate(hoje.year, hoje.month, 1))

    def _aplicar_preset_ultimos_24m(self) -> None:
        hoje = date.today()
        ano = hoje.year - 2
        mes = hoje.month
        if ano < 1:
            ano = 1
        self.date_inicio.setDate(QDate(ano, mes, 1))
        self.date_fim.setDate(QDate(hoje.year, hoje.month, 1))

    def _aplicar_preset_ano_corrente(self) -> None:
        ano = date.today().year
        self.date_inicio.setDate(QDate(ano, 1, 1))
        self.date_fim.setDate(QDate(ano, 12, 1))

    def _aplicar_preset_ano_anterior(self) -> None:
        ano = date.today().year - 1
        self.date_inicio.setDate(QDate(ano, 1, 1))
        self.date_fim.setDate(QDate(ano, 12, 1))

    def _aplicar_preset_tudo(self) -> None:
        self.date_inicio.setDate(QDate(2015, 1, 1))
        self.date_fim.setDate(QDate(date.today().year, 12, 1))

    # ------------------------------------------------------------------
    # Coleta de valores
    # ------------------------------------------------------------------

    def _granularidade_key(self) -> str:
        idx = self.combo_gran.currentIndex()
        return self._GRAN_KEYS[idx] if 0 <= idx < len(self._GRAN_KEYS) else "mensal"

    def _complementos_selecionados(self) -> list[str]:
        result = []
        for i in range(self.lista_compl.count()):
            item = self.lista_compl.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.text())
        return result

    def _montar_dict(self) -> dict:
        qd_ini = self.date_inicio.date()
        qd_fim = self.date_fim.date()
        inicio = date(qd_ini.year(), qd_ini.month(), 1) if qd_ini.isValid() else None
        fim = date(qd_fim.year(), qd_fim.month(), 1) if qd_fim.isValid() else None
        return {
            "granularidade": self._granularidade_key(),
            "inicio": inicio,
            "fim": fim,
            "complementos": self._complementos_selecionados(),
        }

    def _on_aplicar(self) -> None:
        self.filtrosAlterados.emit(self._montar_dict())
