# ui/pages/dedup_page.py - Dedup page with cluster list, evidence panel, actions
from __future__ import annotations

import json
import uuid
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
    QTextEdit, QGroupBox, QProgressDialog, QMessageBox,
    QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QColor, QBrush


CONF_HIGH   = QColor("#d4edda")   # >= 0.95 green
CONF_MEDIUM = QColor("#fff3cd")   # >= 0.85 yellow
CONF_LOW    = QColor("#f8d7da")   # < 0.85  red


def _conf_color(conf: float) -> QColor:
    if conf >= 0.95:
        return CONF_HIGH
    if conf >= 0.85:
        return CONF_MEDIUM
    return CONF_LOW


class _DedupWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, records):
        super().__init__()
        self._records = records

    def run(self):
        try:
            from paperpilot.core.dedup import run_dedup
            clusters = run_dedup(self._records)
            self.finished.emit(clusters)
        except Exception as e:
            self.error.emit(str(e))


class DedupPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._clusters = []
        self._build_ui()

    def set_project(self, project):
        self._project = project
        self._run_btn.setEnabled(True)
        self._status_lbl.setText("Project loaded. Click Run Dedup to start.")
        self._load_existing_clusters()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        self._run_btn = QPushButton("Run Dedup")
        self._run_btn.setEnabled(False)
        self._run_btn.setStyleSheet(
            "padding:6px 16px; background:#4a9eff; color:#fff; border-radius:4px; border:none;"
        )
        self._run_btn.clicked.connect(self._run_dedup)

        self._status_lbl = QLabel("No project open.")
        self._stats_lbl  = QLabel("")

        toolbar.addWidget(self._run_btn)
        toolbar.addWidget(self._status_lbl)
        toolbar.addStretch()
        toolbar.addWidget(self._stats_lbl)
        layout.addLayout(toolbar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # Splitter: cluster list | detail panel
        splitter = QSplitter(Qt.Horizontal)

        # Left: cluster tree
        left = QGroupBox("Duplicate Clusters")
        left_layout = QVBoxLayout(left)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Cluster", "Conf", "Members"])
        self._tree.setColumnWidth(0, 380)
        self._tree.setColumnWidth(1, 60)
        self._tree.setColumnWidth(2, 60)
        self._tree.itemSelectionChanged.connect(self._on_cluster_selected)
        left_layout.addWidget(self._tree)
        splitter.addWidget(left)

        # Right: detail panel
        right = QGroupBox("Cluster Detail")
        right_layout = QVBoxLayout(right)

        self._detail_title = QLabel("Select a cluster to view details.")
        self._detail_title.setWordWrap(True)
        self._detail_title.setStyleSheet("font-weight:bold;")
        right_layout.addWidget(self._detail_title)

        self._evidence_box = QTextEdit()
        self._evidence_box.setReadOnly(True)
        self._evidence_box.setPlaceholderText("Evidence will appear here...")
        right_layout.addWidget(self._evidence_box, 1)

        btn_row = QHBoxLayout()
        self._accept_btn = QPushButton("Accept Cluster")
        self._accept_btn.setEnabled(False)
        self._accept_btn.setStyleSheet(
            "padding:5px 12px; background:#28a745; color:#fff; border-radius:4px; border:none;"
        )
        self._accept_btn.clicked.connect(self._accept_cluster)

        self._split_btn = QPushButton("Split (Not Duplicates)")
        self._split_btn.setEnabled(False)
        self._split_btn.setStyleSheet(
            "padding:5px 12px; background:#dc3545; color:#fff; border-radius:4px; border:none;"
        )
        self._split_btn.clicked.connect(self._split_cluster)

        btn_row.addWidget(self._accept_btn)
        btn_row.addWidget(self._split_btn)
        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setSizes([550, 400])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    def _run_dedup(self):
        if not self._project:
            return

        from paperpilot.core.repositories import RecordRepository
        repo = RecordRepository(self._project.conn)
        records = [r.model_dump() for r in repo.list_all()]

        if not records:
            QMessageBox.information(self, "Dedup", "No records to deduplicate.")
            return

        dlg = QProgressDialog("Running deduplication...", None, 0, 0, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.show()

        self._thread = QThread()
        self._worker = _DedupWorker(records)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_dedup_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(dlg.close)
        self._thread.start()

    def _on_dedup_finished(self, clusters):
        self._clusters = clusters
        self._save_clusters(clusters)
        self._populate_tree(clusters)
        n_clusters = len(clusters)
        n_members  = sum(len(c.member_ids) for c in clusters)
        self._stats_lbl.setText(
            f"Clusters: {n_clusters}  |  Records in clusters: {n_members}"
        )
        self._status_lbl.setText("Dedup complete.")

    def _save_clusters(self, clusters):
        if not self._project:
            return
        conn = self._project.conn
        conn.execute("DELETE FROM dedup_members")
        conn.execute("DELETE FROM dedup_clusters")
        for c in clusters:
            conn.execute(
                """INSERT OR REPLACE INTO dedup_clusters
                   (id, confidence, evidence_json, canonical_record_id, created_at)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (c.id, c.confidence, c.evidence_json, c.canonical_record_id)
            )
            for rid in c.member_ids:
                conn.execute(
                    "INSERT OR REPLACE INTO dedup_members (cluster_id, record_id) VALUES (?, ?)",
                    (c.id, rid)
                )
        conn.commit()

    def _load_existing_clusters(self):
        if not self._project:
            return
        conn = self._project.conn
        rows = conn.execute("SELECT * FROM dedup_clusters").fetchall()
        if not rows:
            return
        from paperpilot.core.dedup.matching import DedupCluster
        clusters = []
        for row in rows:
            members = [r[0] for r in conn.execute(
                "SELECT record_id FROM dedup_members WHERE cluster_id=?", (row["id"],)
            ).fetchall()]
            c = DedupCluster(
                id=row["id"],
                confidence=row["confidence"],
                evidence_json=row["evidence_json"] or "{}",
                canonical_record_id=row["canonical_record_id"],
                member_ids=members,
            )
            clusters.append(c)
        self._clusters = clusters
        self._populate_tree(clusters)

    def _populate_tree(self, clusters):
        self._tree.clear()
        for c in clusters:
            conf_str = f"{c.confidence:.2f}"
            canonical_title = self._get_title(c.canonical_record_id)
            top = QTreeWidgetItem([canonical_title[:60], conf_str, str(len(c.member_ids))])
            color = _conf_color(c.confidence)
            for col in range(3):
                top.setBackground(col, QBrush(color))
            top.setData(0, Qt.UserRole, c)
            for rid in c.member_ids:
                title = self._get_title(rid)
                child = QTreeWidgetItem([f"  {title[:55]}", "", ""])
                child.setData(0, Qt.UserRole, rid)
                top.addChild(child)
            self._tree.addTopLevelItem(top)

    def _get_title(self, record_id: str) -> str:
        if not self._project or not record_id:
            return record_id or ""
        row = self._project.conn.execute(
            "SELECT title FROM records WHERE id=?", (record_id,)
        ).fetchone()
        return (row["title"] or record_id) if row else record_id

    def _on_cluster_selected(self):
        items = self._tree.selectedItems()
        if not items:
            return
        item = items[0]
        cluster = item.data(0, Qt.UserRole)
        if not isinstance(cluster, object) or not hasattr(cluster, "evidence_json"):
            return
        self._current_cluster = cluster
        self._detail_title.setText(
            f"Canonical: {self._get_title(cluster.canonical_record_id)}\n"
            f"Confidence: {cluster.confidence:.2f}  |  Members: {len(cluster.member_ids)}"
        )
        try:
            ev = json.loads(cluster.evidence_json or "{}")
            self._evidence_box.setText(json.dumps(ev, indent=2, ensure_ascii=False))
        except Exception:
            self._evidence_box.setText(cluster.evidence_json or "")
        self._accept_btn.setEnabled(True)
        self._split_btn.setEnabled(True)

    def _accept_cluster(self):
        if not hasattr(self, "_current_cluster"):
            return
        QMessageBox.information(self, "Accepted", "Cluster accepted. Canonical record retained.")

    def _split_cluster(self):
        if not hasattr(self, "_current_cluster"):
            return
        c = self._current_cluster
        if self._project:
            conn = self._project.conn
            conn.execute("DELETE FROM dedup_members WHERE cluster_id=?", (c.id,))
            conn.execute("DELETE FROM dedup_clusters WHERE id=?", (c.id,))
            conn.commit()
        self._populate_tree([x for x in self._clusters if x.id != c.id])
        QMessageBox.information(self, "Split", "Cluster removed. Records treated as distinct.")
