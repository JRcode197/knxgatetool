"""Qt desktop interface for KNXGateTool."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QStandardPaths, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QScrollArea, QSplitter, QStatusBar, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .gateway import GatewayWorker
from .models import Device, Registry, VALID_KINDS, clean_id
from .protocol import ACTIONS, CODE_TO_KIND, decode_telegram

COLUMNS = ("ID", "Nome / descrizione", "Categoria", "Tipo", "maxP",
           "Stato", "Ultimo comando")
STYLE = """
QMainWindow, QWidget { background-color: #101722; color: #E8EFF7;
    font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif;
    font-size: 13px; }
QGroupBox { border: 1px solid #324055; border-radius: 12px;
    margin-top: 13px; padding: 17px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px;
    padding: 0px 8px; color: #B9CEE3; }
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {
    background: #182436; border: 1px solid #34455B; border-radius: 8px;
    padding: 7px; color: #EDF5FF; selection-background-color: #1D6F7B;
}
QTableWidget { gridline-color: #28394D; alternate-background-color: #1B293B; }
QHeaderView::section { color: #C8DAEC; background: #223146;
    border: none; border-bottom: 1px solid #40566F; padding: 10px; }
QPushButton { background: #27394D; color: #E9F4FE;
    border: 1px solid #42586F; border-radius: 8px;
    padding: 9px 12px; font-weight: 600; }
QPushButton:hover { background: #385269; }
QPushButton:pressed { background: #243D53; }
QPushButton:disabled { color: #66798D; background: #1B2735;
    border-color: #293A4C; }
QPushButton[primary="true"] { background: #14A5A6; color: #071B24;
    border-color: #23B6B8; }
QPushButton[primary="true"]:hover { background: #4DC4C4; }
QPushButton[primary="true"]:disabled { background: #254D56; color: #718D97; }
QTabWidget::pane { border: 1px solid #28394D; border-radius: 8px; }
QTabBar::tab { color: #B0C4D9; padding: 13px 22px;
    background: #172334; border-radius: 7px; margin-right: 4px; }
QTabBar::tab:selected { color: #64E1D9; background: #24384A; }
QScrollBar:vertical { background: #111B2B; width: 10px; }
QScrollBar::handle:vertical { background: #40556B; border-radius: 4px; }
QCheckBox { spacing: 8px; }
QStatusBar { color: #AFC5D9; }
"""


def create_button(label: str, callback, primary: bool = False) -> QPushButton:
    button = QPushButton(label)
    button.setProperty("primary", primary)
    button.clicked.connect(callback)
    return button


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KNXGateTool  •  KNX / SCS Gateway")
        self.resize(1450, 880)
        self.setMinimumSize(1010, 650)
        self.setStyleSheet(STYLE)
        self.settings = QSettings("KNXGateTool", "KNXGateTool")
        location = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        self.data_dir = Path(location) if location else Path.home() / ".knxgatetool"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.data_dir / "devices.json"
        self.registry = Registry()
        self.connected = False
        self.monitoring = False
        self.transferring = False
        self.gate = "UNKNOWN"
        self._build_ui()
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(1500)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save_registry)
        if self.registry_path.exists():
            try:
                self.registry.import_json(self.registry_path)
            except Exception as exc:
                self._log(f"ATTENZIONE: archivio locale non caricato: {exc}")
        self._refresh_table()
        self._apply_state()

        self.worker = GatewayWorker(self)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.monitoring.connect(self._on_monitoring)
        self.worker.received.connect(self._on_frame)
        self.worker.log_line.connect(self._log)
        self.worker.failure.connect(self._on_error)
        self.worker.progress.connect(self._set_progress)
        self.worker.download_ready.connect(self._on_download)
        self.worker.upload_complete.connect(self._on_upload)
        self.worker.start()
        self._log(f"KNXGateTool pronto. Dati locali: {self.data_dir}")

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 14, 20, 12)
        layout.setSpacing(13)

        head = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("◈  KNXGateTool")
        font = QFont()
        font.setPointSize(23)
        font.setBold(True)
        title.setFont(font)
        brand.addWidget(title)
        subtitle = QLabel("Gateway KNX / SCS   ·   Monitor e gestione dispositivi")
        subtitle.setStyleSheet("color: #9EB7D0; font-size: 12px;")
        brand.addWidget(subtitle)
        head.addLayout(brand)
        head.addStretch(1)
        self.status_badge = QLabel("●  Scollegato")
        self.status_badge.setStyleSheet(
            "background: #442C35; color: #FFABB9; padding: 10px 17px;"
            " border-radius: 12px; font-weight: 700;")
        head.addWidget(self.status_badge)
        layout.addLayout(head)

        connection = QGroupBox("Connessione al gateway")
        bar = QHBoxLayout(connection)
        bar.setSpacing(9)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["TCP", "Seriale"])
        self.mode_combo.setCurrentText(self.settings.value("mode", "TCP"))
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        self.mode_combo.setMinimumWidth(105)
        bar.addWidget(self.mode_combo)
        self.host_edit = QLineEdit(self.settings.value("host", "192.168.1.100"))
        self.host_edit.setPlaceholderText("Indirizzo IP")
        self.host_edit.setMinimumWidth(145)
        bar.addWidget(self.host_edit, 2)
        self.port_edit = QLineEdit(str(self.settings.value("port", "5045")))
        self.port_edit.setMaximumWidth(90)
        bar.addWidget(self.port_edit)
        self.serial_combo = QComboBox()
        self.serial_combo.setEditable(True)
        self.serial_combo.setMinimumWidth(145)
        bar.addWidget(self.serial_combo, 2)
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "19200", "57600", "38400"])
        self.baud_combo.setCurrentText(str(self.settings.value("baud", "115200")))
        bar.addWidget(self.baud_combo)
        self.refresh_ports_button = create_button("⟳", self._refresh_ports)
        self.refresh_ports_button.setToolTip("Aggiorna porte seriali")
        bar.addWidget(self.refresh_ports_button)
        self.connect_btn = create_button("Connetti", self._toggle_connect, True)
        bar.addWidget(self.connect_btn)
        self.query_btn = create_button("Firmware", self._query)
        bar.addWidget(self.query_btn)
        self.monitor_combo = QComboBox()
        self.monitor_combo.addItems(["Telegrammi bus", "Seriale ASCII"])
        bar.addWidget(self.monitor_combo)
        self.monitor_btn = create_button("Avvia monitor", self._toggle_monitor)
        bar.addWidget(self.monitor_btn)
        layout.addWidget(connection)
        self._refresh_ports()
        self.serial_combo.setEditText(str(self.settings.value("serial_port", "")))
        self._mode_changed()

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        device_tab = QWidget()
        self.tabs.addTab(device_tab, "Dispositivi")
        device_layout = QVBoxLayout(device_tab)
        device_layout.setContentsMargins(12, 14, 12, 10)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca ID, nome, categoria...")
        self.search.setMaximumWidth(320)
        self.search.textChanged.connect(self._filter_rows)
        toolbar.addWidget(self.search)
        self.count_label = QLabel("0 dispositivi")
        self.count_label.setStyleSheet("color: #A9C8D7;")
        toolbar.addWidget(self.count_label)
        toolbar.addStretch()
        toolbar.addWidget(create_button("+ Nuovo", self._add_device))
        toolbar.addWidget(create_button("Elimina", self._remove_device))
        toolbar.addWidget(create_button("Importa JSON", self._import_json))
        toolbar.addWidget(create_button("Importa VB6", self._import_legacy))
        toolbar.addWidget(create_button("Esporta JSON", self._export_json))
        device_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(37)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in [(0, 80), (2, 130), (3, 76),
                              (4, 65), (5, 95), (6, 120)]:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.itemChanged.connect(self._cell_edited)
        self.table.itemSelectionChanged.connect(self._update_actions)
        splitter.addWidget(self.table)

        side = QWidget()
        side.setMinimumWidth(220)
        side.setMaximumWidth(330)
        side_layout = QVBoxLayout(side)
        selection_group = QGroupBox("Dispositivo selezionato")
        sel_layout = QVBoxLayout(selection_group)
        self.selected_title = QLabel("Seleziona una riga")
        sel_font = QFont()
        sel_font.setPointSize(14)
        sel_font.setBold(True)
        self.selected_title.setFont(sel_font)
        self.selected_title.setWordWrap(True)
        sel_layout.addWidget(self.selected_title)
        self.selected_info = QLabel("Nessun dispositivo")
        self.selected_info.setWordWrap(True)
        self.selected_info.setStyleSheet("color: #A6BBCB;")
        sel_layout.addWidget(self.selected_info)
        side_layout.addWidget(selection_group)

        actions_group = QGroupBox("Comandi memorizzati")
        action_layout = QGridLayout(actions_group)
        self.action_buttons: dict[str, QPushButton] = {}
        for index, action in enumerate(ACTIONS):
            button = create_button(action, lambda _=False, a=action: self._send_action(a))
            button.setMinimumHeight(43)
            button.setToolTip("Richiede un telegramma acquisito dal monitor")
            self.action_buttons[action] = button
            action_layout.addWidget(button, index // 2, index % 2)
        side_layout.addWidget(actions_group)
        notice = QLabel("I comandi sono inviati solo se il telegramma è stato "
                        "acquisito o ricostruito da un evento noto. "
                        "I telegrammi inferiti richiedono conferma.")
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #91A9BF; padding: 5px;")
        side_layout.addWidget(notice)
        side_layout.addStretch(1)
        splitter.addWidget(side)
        splitter.setSizes([1050, 285])
        device_layout.addWidget(splitter, 1)

        transfer = QHBoxLayout()
        self.download_btn = create_button("↓  Scarica dispositivi dal gateway", self._download)
        self.upload_btn = create_button("↑  Carica sul gateway", self._upload)
        transfer.addWidget(self.download_btn)
        transfer.addWidget(self.upload_btn)
        transfer.addStretch()
        self.fw_label = QLabel("Firmware: —")
        self.fw_label.setStyleSheet("color: #9CB9C8;")
        transfer.addWidget(self.fw_label)
        device_layout.addLayout(transfer)

        monitor_tab = QWidget()
        self.tabs.addTab(monitor_tab, "Monitor / log")
        log_layout = QVBoxLayout(monitor_tab)
        log_layout.setContentsMargins(12, 14, 12, 12)
        log_bar = QHBoxLayout()
        log_bar.addWidget(QLabel("Eventi e traffico di comunicazione"))
        log_bar.addStretch()
        log_bar.addWidget(create_button("Esporta log", self._export_log))
        log_bar.addWidget(create_button("Pulisci", self._clear_log))
        log_layout.addLayout(log_bar)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.logs.setFont(QFont("Consolas", 11))
        self.logs.document().setMaximumBlockCount(20000)
        log_layout.addWidget(self.logs)

        settings_tab = QWidget()
        self.tabs.addTab(settings_tab, "Impostazioni / aiuto")
        settings_outer = QVBoxLayout(settings_tab)
        settings_outer.setContentsMargins(17, 20, 17, 20)
        settings_outer.setSpacing(15)
        gateway_group = QGroupBox("Parametri gateway (solo TCP)")
        gateway_layout = QVBoxLayout(gateway_group)
        gateway_layout.addWidget(QLabel(
            "La modalità del gateway è identificata durante l'interrogazione @q. "
            "Le seguenti funzioni agiscono direttamente sul firmware ESP."))
        settings_row = QHBoxLayout()
        settings_row.addWidget(create_button("Frequenza 80 MHz",
                                              lambda: self._frequency("80")))
        settings_row.addWidget(create_button("Frequenza 160 MHz",
                                              lambda: self._frequency("160")))
        settings_row.addStretch()
        gateway_layout.addLayout(settings_row)
        self.cover_checkbox = QCheckBox(
            "Percentuale tapparelle durante upload (tipo TAP 9 / UPD 19)")
        gateway_layout.addWidget(self.cover_checkbox)
        settings_outer.addWidget(gateway_group)
        help_group = QGroupBox("Compatibilità e precauzioni")
        help_layout = QVBoxLayout(help_group)
        for paragraph in [
            "Compatibile con il protocollo specifico ESP_KNXGATE / ESP_SCSGATE "
            "di Guido Pagani; non usa KNXnet/IP.",
            "La modalità seriale usa 115200 baud per impostazione predefinita. "
            "Il TCP usa la porta 5045. Il monitor si avvia solo dopo una query "
            "firmware e un handshake completi.",
            "Per modificare un nome, categoria, tipo o maxP fai doppio clic "
            "nella tabella. Le variazioni vengono salvate localmente.",
            "Il download legge la configurazione del gateway senza cancellarla. "
            "L'upload sovrascrive tutti i dispositivi del gateway: viene "
            "eseguito automaticamente un backup remoto prima della cancellazione.",
            "Il flash firmware non è implementato: necessita di test e procedure "
            "di recupero su hardware reale. Non esporre il gateway su Internet.",
            "I telegrammi ricostruiti derivano dai byte osservati e dalla "
            "logica del programma VB6 V6.0. Verificarli sull'impianto reale.",
        ]:
            line = QLabel("•  " + paragraph)
            line.setWordWrap(True)
            line.setStyleSheet("color: #BDD0E0; padding: 4px;")
            help_layout.addWidget(line)
        settings_outer.addWidget(help_group)
        self.data_path_label = QLabel(f"Dati locali: {self.data_dir}")
        self.data_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        settings_outer.addWidget(self.data_path_label)
        settings_outer.addStretch(1)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Pronto")

    def _log(self, message: str) -> None:
        if not hasattr(self, "logs"):
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logs.appendPlainText(f"[{stamp}]  {message}")

    def _set_progress(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        self._log(message)

    def _mode_changed(self) -> None:
        is_tcp = self.mode_combo.currentText() == "TCP"
        for widget in (self.host_edit, self.port_edit):
            widget.setVisible(is_tcp)
        for widget in (self.serial_combo, self.baud_combo, self.refresh_ports_button):
            widget.setVisible(not is_tcp)
        if hasattr(self, "download_btn"):
            self._apply_state()

    def _refresh_ports(self) -> None:
        from serial.tools import list_ports
        old = self.serial_combo.currentText()
        self.serial_combo.clear()
        self.serial_combo.addItems([port.device for port in list_ports.comports()])
        if old:
            self.serial_combo.setEditText(old)

    def _settings_save(self) -> None:
        for key, value in [
            ("mode", self.mode_combo.currentText()),
            ("host", self.host_edit.text()),
            ("port", self.port_edit.text()),
            ("serial_port", self.serial_combo.currentText()),
            ("baud", self.baud_combo.currentText()),
        ]:
            self.settings.setValue(key, value)

    def _toggle_connect(self) -> None:
        if self.connected:
            self.worker.submit("disconnect")
            return
        self._settings_save()
        self.connect_btn.setEnabled(False)
        self.statusBar().showMessage("Connessione in corso...")
        self.worker.submit("connect", {
            "mode": self.mode_combo.currentText(),
            "host": self.host_edit.text().strip(),
            "port": self.port_edit.text(),
            "serial_port": self.serial_combo.currentText(),
            "baud": self.baud_combo.currentText(),
        })

    def _on_connected(self, firmware: str, gate: str) -> None:
        self.connected = True
        self.gate = gate
        self.fw_label.setText(f"Firmware: {firmware[:80]}  ·  {gate}")
        self.status_badge.setText(f"●  Connesso · {gate}")
        self.status_badge.setStyleSheet(
            "background: #173D3A; color: #74ECD6; padding: 10px 17px;"
            " border-radius: 12px; font-weight: 700;")
        self.statusBar().showMessage("Connesso", 5000)
        self._apply_state()

    def _on_disconnected(self) -> None:
        self.connected = False
        self.monitoring = False
        self.gate = "UNKNOWN"
        self.status_badge.setText("●  Scollegato")
        self.status_badge.setStyleSheet(
            "background: #442C35; color: #FFABB9; padding: 10px 17px;"
            " border-radius: 12px; font-weight: 700;")
        self._apply_state()

    def _on_monitoring(self, active: bool) -> None:
        self.monitoring = active
        if active:
            self.tabs.setCurrentIndex(1)
        self._apply_state()

    def _on_error(self, message: str) -> None:
        self.transferring = False
        self._apply_state()
        self.statusBar().showMessage("Errore: " + message, 15000)
        QMessageBox.warning(self, "Errore KNXGateTool", message)

    def _query(self) -> None:
        self.worker.submit("query")

    def _toggle_monitor(self) -> None:
        if self.monitoring:
            self.worker.submit("stop_monitor")
        else:
            self.worker.submit("start_monitor",
                               "ascii" if self.monitor_combo.currentIndex() == 1 else "bus")

    def _apply_state(self) -> None:
        usable = self.connected and not self.transferring
        idle_tcp = usable and not self.monitoring and self.mode_combo.currentText() == "TCP"
        self.connect_btn.setEnabled(not self.transferring)
        self.connect_btn.setText("Disconnetti" if self.connected else "Connetti")
        self.query_btn.setEnabled(usable and not self.monitoring)
        self.monitor_btn.setEnabled(usable)
        self.monitor_btn.setText("Ferma monitor" if self.monitoring else "Avvia monitor")
        self.monitor_combo.setEnabled(usable and not self.monitoring)
        self.download_btn.setEnabled(idle_tcp)
        self.upload_btn.setEnabled(idle_tcp and bool(self.registry.devices)
                                   and self.gate in ("KNX", "SCS"))
        for widget in (self.mode_combo, self.host_edit, self.port_edit,
                       self.serial_combo, self.baud_combo, self.refresh_ports_button):
            widget.setEnabled(not self.connected and not self.transferring)
        self._update_actions()

    def _selected_device(self) -> Device | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.table.item(row, 0)
        return self.registry.devices.get(item.text()) if item else None

    def _update_actions(self) -> None:
        device = self._selected_device()
        self.selected_title.setText(
            f"{device.id}  ·  {device.name or 'Senza nome'}"
            if device else "Seleziona una riga")
        if device:
            self.selected_info.setText(
                f"Tipo: {device.kind}\nCategoria: {device.category}\n"
                f"Stato: {device.status or '—'}\n"
                f"Telegrammi disponibili: {', '.join(device.telegrams) or 'nessuno'}")
        else:
            self.selected_info.setText("Nessun dispositivo")
        for action, button in self.action_buttons.items():
            enabled = bool(device and self.connected and self.monitoring
                           and not self.transferring and action in device.telegrams
                           and self.monitor_combo.currentIndex() == 0)
            button.setEnabled(enabled)
            button.setText(action + (" *" if device and action in device.inferred else ""))

    def _refresh_table(self, focus_id: str | None = None) -> None:
        selected = focus_id or (self._selected_device().id
                                if self.table.rowCount() and self._selected_device() else "")
        self.table.blockSignals(True)
        devices = self.registry.values()
        self.table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            values = [device.id, device.name, device.category, device.kind,
                      device.maxp, device.status, device.last_command]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col in (0, 5, 6):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 5:
                    if value == "ON":
                        item.setForeground(QColor("#65D7BB"))
                    elif value == "OFF":
                        item.setForeground(QColor("#EFACB5"))
                if col == 0:
                    item.setForeground(QColor("#77DDDF"))
                self.table.setItem(row, col, item)
            if device.id == selected:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.count_label.setText(f"{len(devices)} dispositivi")
        self._filter_rows()
        self._update_actions()
        if hasattr(self, "upload_btn"):
            self._apply_state()

    def _filter_rows(self) -> None:
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            text = " ".join((self.table.item(row, col).text()
                             if self.table.item(row, col) else "")
                            for col in (0, 1, 2, 3))
            self.table.setRowHidden(row, bool(query and query not in text.casefold()))

    def _cell_edited(self, item: QTableWidgetItem) -> None:
        id_item = self.table.item(item.row(), 0)
        if not id_item:
            return
        device = self.registry.devices.get(id_item.text())
        if not device:
            return
        value = item.text().strip()
        col = item.column()
        if col == 1:
            device.name = value
        elif col == 2:
            device.category = value or "Altro"
        elif col == 3:
            if value.upper() not in VALID_KINDS:
                QMessageBox.warning(self, "Tipo non valido",
                                    "Tipi ammessi: " + ", ".join(VALID_KINDS))
                self._refresh_table(device.id)
                return
            device.kind = value.upper()
        elif col == 4:
            device.maxp = value or "0"
        self._schedule_save()
        self._update_actions()

    def _schedule_save(self) -> None:
        self.save_timer.start()

    def _save_registry(self) -> None:
        try:
            self.registry.export(self.registry_path)
        except Exception as exc:
            self._log(f"Errore salvataggio locale: {exc}")

    def _add_device(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Aggiungi dispositivo", "ID esadecimale (es. 0EA1):")
        if not ok:
            return
        try:
            new_id = clean_id(text)
            if new_id in self.registry.devices:
                raise ValueError("Dispositivo già presente")
            self.registry.upsert(Device(new_id))
        except ValueError as exc:
            QMessageBox.warning(self, "ID non valido", str(exc))
            return
        self._refresh_table(new_id)
        self._schedule_save()

    def _remove_device(self) -> None:
        device = self._selected_device()
        if not device:
            return
        if QMessageBox.question(self, "Elimina dispositivo",
                f"Rimuovere {device.id} ({device.name}) dall'archivio locale?\n"
                "Il gateway non sarà modificato.") != QMessageBox.StandardButton.Yes:
            return
        del self.registry.devices[device.id]
        self._refresh_table()
        self._schedule_save()

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importa dispositivi", "", "JSON (*.json);;Tutti i file (*)")
        if path:
            try:
                count = self.registry.import_json(Path(path))
                self._refresh_table()
                self._schedule_save()
                self._log(f"Importati {count} dispositivi da {path}")
            except Exception as exc:
                QMessageBox.warning(self, "Importazione fallita", str(exc))

    def _import_legacy(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importa griglia VB6", "", "File VB6 (*.txt);;Tutti i file (*)")
        if path:
            try:
                count = self.registry.import_legacy(Path(path))
                self._refresh_table()
                self._schedule_save()
                self._log(f"Importati {count} dispositivi VB6 da {path}")
            except Exception as exc:
                QMessageBox.warning(self, "Importazione fallita", str(exc))

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Esporta dispositivi", "ByMe_Lab_dispositivi.json",
            "JSON (*.json)")
        if path:
            try:
                self.registry.export(Path(path))
                self._log("Esportazione completata: " + path)
            except Exception as exc:
                QMessageBox.warning(self, "Esportazione fallita", str(exc))

    def _download(self) -> None:
        self.transferring = True
        self._apply_state()
        self._log("Inizio download del catalogo remoto")
        self.worker.submit("download")

    def _on_download(self, records) -> None:
        try:
            imported = 0
            for record in records:
                self.registry.upsert(Device.from_mapping(record))
                imported += 1
            self._refresh_table()
            self._schedule_save()
            self._log(f"Download completato: {imported} dispositivi (uniti all'archivio locale)")
            self.statusBar().showMessage(f"Download completato: {imported} dispositivi", 9000)
        except Exception as exc:
            QMessageBox.warning(self, "Download parzialmente interpretato", str(exc))
        finally:
            self.transferring = False
            self._apply_state()

    def _upload(self) -> None:
        if self.gate not in ("KNX", "SCS"):
            return
        records = [d.to_mapping() for d in self.registry.values()]
        confirm = QMessageBox.warning(
            self, "ATTENZIONE: sostituzione dispositivi",
            "L'upload CANCELLERÀ e RISCRIVERÀ l'intera configurazione dispositivi "
            "del gateway.\n\n"
            "Il programma tenta prima un download completo e salva un backup "
            "locale della configurazione remota. Se il backup non riesce, "
            "l'upload viene annullato.\n\n"
            f"Procedere con {len(records)} dispositivi ({self.gate})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self.data_dir / "backups" / f"gateway_before_upload_{timestamp}.json"
        self.transferring = True
        self._apply_state()
        self._log("Upload richiesto: backup remoto preventivo obbligatorio")
        self.worker.submit("upload",
            (records, self.gate, self.cover_checkbox.isChecked(), str(backup)))

    def _on_upload(self, backup_path: str) -> None:
        self.transferring = False
        self._apply_state()
        self._log(f"Upload completato; backup remoto in {backup_path}")
        QMessageBox.information(
            self, "Upload completato",
            f"Configurazione inviata e commit confermato.\nBackup precedente:\n{backup_path}")

    def _frequency(self, value: str) -> None:
        if not (self.connected and not self.monitoring
                and self.mode_combo.currentText() == "TCP"):
            QMessageBox.information(self, "Operazione non disponibile",
                                    "Connetti in TCP e ferma prima il monitor.")
            return
        if QMessageBox.question(
            self, "Modifica frequenza", f"Impostare il gateway a {value} MHz?"
        ) == QMessageBox.StandardButton.Yes:
            self.worker.submit("frequency", value)

    def _send_action(self, action: str) -> None:
        device = self._selected_device()
        if not device or not self.monitoring or not self.connected:
            return
        try:
            telegram = device.command_bytes(action)
        except ValueError as exc:
            QMessageBox.warning(self, "Telegramma non disponibile", str(exc))
            return
        if action in device.inferred:
            if QMessageBox.warning(
                self, "Telegramma ricostruito",
                f"Il comando {action} per {device.id} deriva da un altro "
                "telegramma acquisito secondo la logica VB6, non è stato "
                "osservato direttamente. Inviarlo comunque?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            ) != QMessageBox.StandardButton.Yes:
                return
        self.worker.submit("send", telegram)
        self._log(f"Comando richiesto {device.id} {action}")

    def _on_frame(self, raw: bytes) -> None:
        from .protocol import decode_telegram
        self._log("RX  " + raw.hex(" ").upper())
        # Classification depends on currently configured device kind.
        preliminary = decode_telegram(raw)
        if preliminary is None:
            return
        previous = self.registry.devices.get(preliminary.device_id)
        event = decode_telegram(raw, previous.kind if previous else "")
        if not event:
            return
        dev = self.registry.observe(event)
        self._log(f"{event.protocol} {event.device_id}  "
                  f"{event.action or '?'}  cmd={event.command}")
        self._refresh_table(dev.id)
        self._schedule_save()

    def _export_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva log", "knxgatetool_log.txt", "Testo (*.txt)")
        if path:
            try:
                Path(path).write_text(self.logs.toPlainText() + "\n", encoding="utf-8")
            except Exception as exc:
                QMessageBox.warning(self, "Errore salvataggio log", str(exc))

    def _clear_log(self) -> None:
        self.logs.clear()

    def closeEvent(self, event) -> None:
        self._settings_save()
        self._save_registry()
        self.worker.shutdown()
        if not self.worker.wait(4500):
            event.ignore()
            QMessageBox.information(
                self, "Chiusura in corso",
                "Una comunicazione deve terminare prima che il programma "
                "possa essere chiuso. Riprova fra qualche istante.")
            return
        event.accept()
