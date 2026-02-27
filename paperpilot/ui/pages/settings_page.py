# ui/pages/settings_page.py - Settings page: AI Providers + Protocol
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QListWidget, QListWidgetItem, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QCheckBox, QGroupBox, QTextEdit, QFileDialog,
    QMessageBox, QFormLayout, QFrame, QSplitter,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _ConnTestWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, provider):
        super().__init__()
        self._provider = provider

    def run(self):
        try:
            ok, msg = self._provider.test_connection()
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class _ListModelsWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, provider):
        super().__init__()
        self._provider = provider

    def run(self):
        try:
            models = self._provider.list_models()
            self.finished.emit(models)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Provider config panel (OpenAI-compatible)
# ---------------------------------------------------------------------------

class _OpenAIPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(8, 8, 8, 8)

        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. My OpenAI")
        form.addRow("Name:", self._name)

        key_row = QHBoxLayout()
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("sk-...")
        self._show_btn = QPushButton("Show")
        self._show_btn.setFixedWidth(48)
        self._show_btn.setCheckable(True)
        self._show_btn.toggled.connect(
            lambda on: self._api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_row.addWidget(self._api_key)
        key_row.addWidget(self._show_btn)
        form.addRow("API Key:", key_row)

        self._base_url = QLineEdit("https://api.openai.com/v1")
        form.addRow("Base URL:", self._base_url)

        model_row = QHBoxLayout()
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(60)
        self._refresh_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self._model_combo, 1)
        model_row.addWidget(self._refresh_btn)
        form.addRow("Model:", model_row)

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._test)
        self._test_lbl = QLabel("")
        form.addRow(self._test_btn, self._test_lbl)

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._save_btn.setStyleSheet(
            "background:#4a9eff;color:#fff;padding:5px 14px;border-radius:4px;border:none;"
        )
        self._save_btn.clicked.connect(self._save)
        self._del_btn = QPushButton("Delete")
        self._del_btn.setStyleSheet(
            "background:#dc3545;color:#fff;padding:5px 14px;border-radius:4px;border:none;"
        )
        self._del_btn.clicked.connect(self._delete)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        form.addRow(btn_row)

        self._entry_key: str | None = None
        self._settings_page: "SettingsPage | None" = None

    def load(self, entry_key: str, cfg: dict, page: "SettingsPage"):
        self._entry_key = entry_key
        self._settings_page = page
        self._name.setText(cfg.get("name", entry_key))
        self._api_key.setText(cfg.get("api_key", ""))
        self._base_url.setText(cfg.get("base_url", "https://api.openai.com/v1"))
        self._model_combo.clear()
        m = cfg.get("model", "")
        if m:
            self._model_combo.addItem(m)
        self._test_lbl.setText("")

    def _make_provider(self):
        from paperpilot.core.ai.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=self._api_key.text().strip(),
            base_url=self._base_url.text().strip(),
            model=self._model_combo.currentText().strip(),
        )

    def _refresh_models(self):
        self._refresh_btn.setEnabled(False)
        try:
            provider = self._make_provider()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            self._refresh_btn.setEnabled(True)
            return
        self._thread = QThread()
        self._worker = _ListModelsWorker(provider)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_models)
        self._worker.error.connect(lambda e: QMessageBox.warning(self, "Error", e))
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._thread.start()

    def _on_models(self, models: list):
        current = self._model_combo.currentText()
        self._model_combo.clear()
        self._model_combo.addItems(models)
        if current in models:
            self._model_combo.setCurrentText(current)

    def _test(self):
        self._test_btn.setEnabled(False)
        self._test_lbl.setText("Testing...")
        try:
            provider = self._make_provider()
        except Exception as e:
            self._test_lbl.setText(f"ERR: {e}")
            self._test_btn.setEnabled(True)
            return
        self._t_thread = QThread()
        self._t_worker = _ConnTestWorker(provider)
        self._t_worker.moveToThread(self._t_thread)
        self._t_thread.started.connect(self._t_worker.run)
        self._t_worker.finished.connect(self._on_test_done)
        self._t_worker.finished.connect(self._t_thread.quit)
        self._t_thread.finished.connect(lambda: self._test_btn.setEnabled(True))
        self._t_thread.start()

    def _on_test_done(self, ok: bool, msg: str):
        self._test_lbl.setText(("OK: " if ok else "FAIL: ") + msg)
        self._test_lbl.setStyleSheet("color:green;" if ok else "color:red;")

    def _save(self):
        if not self._settings_page or not self._entry_key:
            return
        from paperpilot.core.ai.provider_config import ProviderConfig
        pc = ProviderConfig()
        cfg = pc.load()
        cfg[self._entry_key] = {
            "provider": "openai",
            "name": self._name.text().strip(),
            "api_key": self._api_key.text().strip(),
            "base_url": self._base_url.text().strip(),
            "model": self._model_combo.currentText().strip(),
        }
        pc.save(cfg)
        self._settings_page._reload_providers()

    def _delete(self):
        if not self._settings_page or not self._entry_key:
            return
        if QMessageBox.question(self, "Delete", f"Delete provider '{self._entry_key}'?") \
                != QMessageBox.Yes:
            return
        from paperpilot.core.ai.provider_config import ProviderConfig
        pc = ProviderConfig()
        cfg = pc.load()
        cfg.pop(self._entry_key, None)
        pc.save(cfg)
        self._settings_page._reload_providers()


# ---------------------------------------------------------------------------
# Ollama panel
# ---------------------------------------------------------------------------

class _OllamaPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(8, 8, 8, 8)

        self._name = QLineEdit("Ollama (local)")
        form.addRow("Name:", self._name)

        self._base_url = QLineEdit("http://localhost:11434")
        form.addRow("Base URL:", self._base_url)

        model_row = QHBoxLayout()
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(60)
        self._refresh_btn.clicked.connect(self._refresh_models)
        model_row.addWidget(self._model_combo, 1)
        model_row.addWidget(self._refresh_btn)
        form.addRow("Model:", model_row)

        self._test_btn = QPushButton("Test Connection")
        self._test_btn.clicked.connect(self._test)
        self._test_lbl = QLabel("")
        form.addRow(self._test_btn, self._test_lbl)

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._save_btn.setStyleSheet(
            "background:#4a9eff;color:#fff;padding:5px 14px;border-radius:4px;border:none;"
        )
        self._save_btn.clicked.connect(self._save)
        self._del_btn = QPushButton("Delete")
        self._del_btn.setStyleSheet(
            "background:#dc3545;color:#fff;padding:5px 14px;border-radius:4px;border:none;"
        )
        self._del_btn.clicked.connect(self._delete)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        form.addRow(btn_row)

        self._entry_key: str | None = None
        self._settings_page: "SettingsPage | None" = None

    def load(self, entry_key: str, cfg: dict, page: "SettingsPage"):
        self._entry_key = entry_key
        self._settings_page = page
        self._name.setText(cfg.get("name", entry_key))
        self._base_url.setText(cfg.get("base_url", "http://localhost:11434"))
        self._model_combo.clear()
        m = cfg.get("model", "")
        if m:
            self._model_combo.addItem(m)
        self._test_lbl.setText("")

    def _make_provider(self):
        from paperpilot.core.ai.ollama_provider import OllamaProvider
        return OllamaProvider(
            base_url=self._base_url.text().strip(),
            model=self._model_combo.currentText().strip() or "llama3",
        )

    def _refresh_models(self):
        self._refresh_btn.setEnabled(False)
        self._thread = QThread()
        self._worker = _ListModelsWorker(self._make_provider())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_models)
        self._worker.error.connect(lambda e: QMessageBox.warning(self, "Error", e))
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(lambda: self._refresh_btn.setEnabled(True))
        self._thread.start()

    def _on_models(self, models: list):
        current = self._model_combo.currentText()
        self._model_combo.clear()
        self._model_combo.addItems(models)
        if current in models:
            self._model_combo.setCurrentText(current)

    def _test(self):
        self._test_btn.setEnabled(False)
        self._test_lbl.setText("Testing...")
        self._t_thread = QThread()
        self._t_worker = _ConnTestWorker(self._make_provider())
        self._t_worker.moveToThread(self._t_thread)
        self._t_thread.started.connect(self._t_worker.run)
        self._t_worker.finished.connect(self._on_test_done)
        self._t_worker.finished.connect(self._t_thread.quit)
        self._t_thread.finished.connect(lambda: self._test_btn.setEnabled(True))
        self._t_thread.start()

    def _on_test_done(self, ok: bool, msg: str):
        self._test_lbl.setText(("OK: " if ok else "FAIL: ") + msg)
        self._test_lbl.setStyleSheet("color:green;" if ok else "color:red;")

    def _save(self):
        if not self._settings_page or not self._entry_key:
            return
        from paperpilot.core.ai.provider_config import ProviderConfig
        pc = ProviderConfig()
        cfg = pc.load()
        cfg[self._entry_key] = {
            "provider": "ollama",
            "name": self._name.text().strip(),
            "base_url": self._base_url.text().strip(),
            "model": self._model_combo.currentText().strip(),
        }
        pc.save(cfg)
        self._settings_page._reload_providers()

    def _delete(self):
        if not self._settings_page or not self._entry_key:
            return
        if QMessageBox.question(self, "Delete", f"Delete provider '{self._entry_key}'?") \
                != QMessageBox.Yes:
            return
        from paperpilot.core.ai.provider_config import ProviderConfig
        pc = ProviderConfig()
        cfg = pc.load()
        cfg.pop(self._entry_key, None)
        pc.save(cfg)
        self._settings_page._reload_providers()


# ---------------------------------------------------------------------------
# Main SettingsPage
# ---------------------------------------------------------------------------

class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._build_ui()
        self._reload_providers()

    def set_project(self, project):
        self._project = project
        self._load_protocol()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # --- Tab 1: AI Providers ---
        ai_tab = QWidget()
        ai_layout = QHBoxLayout(ai_tab)

        # Left: provider list
        left = QGroupBox("Configured Providers")
        left_layout = QVBoxLayout(left)
        self._provider_list = QListWidget()
        self._provider_list.currentRowChanged.connect(self._on_provider_selected)
        left_layout.addWidget(self._provider_list)

        add_row = QHBoxLayout()
        add_openai_btn = QPushButton("+ OpenAI / Compat")
        add_openai_btn.clicked.connect(self._add_openai)
        add_ollama_btn = QPushButton("+ Ollama")
        add_ollama_btn.clicked.connect(self._add_ollama)
        add_row.addWidget(add_openai_btn)
        add_row.addWidget(add_ollama_btn)
        left_layout.addLayout(add_row)
        left.setFixedWidth(220)
        ai_layout.addWidget(left)

        # Right: stacked panels
        self._stack = QStackedWidget()
        placeholder = QLabel("Select a provider to configure.")
        placeholder.setAlignment(Qt.AlignCenter)
        self._stack.addWidget(placeholder)   # index 0
        ai_layout.addWidget(self._stack, 1)

        tabs.addTab(ai_tab, "AI Providers")

        # --- Tab 2: Protocol ---
        proto_tab = QWidget()
        proto_layout = QVBoxLayout(proto_tab)

        proto_btn_row = QHBoxLayout()
        load_btn = QPushButton("Load from file...")
        load_btn.clicked.connect(self._load_protocol_file)
        save_btn = QPushButton("Save to project")
        save_btn.clicked.connect(self._save_protocol)
        reset_btn = QPushButton("Reset to default")
        reset_btn.clicked.connect(self._reset_protocol)
        proto_btn_row.addWidget(load_btn)
        proto_btn_row.addWidget(save_btn)
        proto_btn_row.addWidget(reset_btn)
        proto_btn_row.addStretch()
        proto_layout.addLayout(proto_btn_row)

        self._protocol_editor = QTextEdit()
        self._protocol_editor.setFont(QFont("Courier New", 10))
        self._protocol_editor.setPlaceholderText("Protocol JSON will appear here...")
        proto_layout.addWidget(self._protocol_editor)

        tabs.addTab(proto_tab, "Screening Protocol")

        # Internal tracking
        self._panel_map: dict[int, tuple[str, QWidget]] = {}  # row -> (key, panel)

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    def _reload_providers(self):
        from paperpilot.core.ai.provider_config import ProviderConfig
        pc = ProviderConfig()
        cfg = pc.load()

        # Clear stack (keep index 0 placeholder)
        while self._stack.count() > 1:
            w = self._stack.widget(1)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._provider_list.clear()
        self._panel_map.clear()

        for key, entry in cfg.items():
            ptype = entry.get("provider", "openai")
            label = entry.get("name", key)
            item = QListWidgetItem(label)
            row = self._provider_list.count()
            self._provider_list.addItem(item)

            if ptype == "ollama":
                panel = _OllamaPanel()
            else:
                panel = _OpenAIPanel()
            panel.load(key, entry, self)
            self._stack.addWidget(panel)  # index = row + 1
            self._panel_map[row] = (key, panel)

        if self._provider_list.count() > 0:
            self._provider_list.setCurrentRow(0)

    def _on_provider_selected(self, row: int):
        if row < 0:
            self._stack.setCurrentIndex(0)
            return
        self._stack.setCurrentIndex(row + 1)

    def _add_openai(self):
        from paperpilot.core.ai.provider_config import ProviderConfig
        import uuid
        pc = ProviderConfig()
        cfg = pc.load()
        key = f"openai_{uuid.uuid4().hex[:6]}"
        cfg[key] = {"provider": "openai", "name": "New OpenAI", "api_key": "", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"}
        pc.save(cfg)
        self._reload_providers()

    def _add_ollama(self):
        from paperpilot.core.ai.provider_config import ProviderConfig
        import uuid
        pc = ProviderConfig()
        cfg = pc.load()
        key = f"ollama_{uuid.uuid4().hex[:6]}"
        cfg[key] = {"provider": "ollama", "name": "Ollama (local)", "base_url": "http://localhost:11434", "model": "llama3"}
        pc.save(cfg)
        self._reload_providers()

    # ------------------------------------------------------------------
    # Protocol
    # ------------------------------------------------------------------

    def _load_protocol(self):
        from paperpilot.core.screening.protocol import load_default_protocol
        try:
            proto = load_default_protocol()
            self._protocol_editor.setText(json.dumps(proto, indent=2, ensure_ascii=False))
        except Exception as e:
            self._protocol_editor.setPlaceholderText(f"Error loading protocol: {e}")

    def _load_protocol_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Protocol", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._protocol_editor.setText(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _save_protocol(self):
        if not self._project:
            QMessageBox.warning(self, "No Project", "Please open a project first.")
            return
        try:
            data = json.loads(self._protocol_editor.toPlainText())
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid JSON", str(e))
            return
        out = Path(self._project.project_path) / "protocol.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        QMessageBox.information(self, "Saved", f"Protocol saved to {out}")

    def _reset_protocol(self):
        self._load_protocol()
