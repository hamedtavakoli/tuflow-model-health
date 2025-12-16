"""Dock widget UI for running the TUFLOW QA/QC pipeline inside QGIS."""

import json
import traceback
from pathlib import Path
from typing import List, Optional

from qgis.PyQt.QtCore import Qt, QSettings, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QStandardItem, QStandardItemModel
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication, QgsMessageLog, QgsTask, Qgis

from .vendor.tuflow_qaqc.api import RunResult, render_html_report, run_qaqc
from .vendor.tuflow_qaqc.parsing import find_wildcards_in_filename
from .vendor.tuflow_qaqc.core import Severity
from .vendor.tuflow_qaqc.wildcards import validate_wildcards


PLUGIN_SETTINGS_KEY = "TuflowModelHealth"
TREE_PATH_ROLE = Qt.UserRole + 10


class QaqcTask(QgsTask):
    """Background task wrapping the run_qaqc API."""

    progressMessage = pyqtSignal(str)

    def __init__(
        self,
        tcf_path: str,
        run_test: bool,
        tuflow_exe: str,
        wildcards: dict,
        on_finished,
    ):
        super().__init__("TUFLOW Model Health QA/QC", QgsTask.CanCancel)
        self.tcf_path = tcf_path
        self.run_test = run_test
        self.tuflow_exe = tuflow_exe
        self.wildcards = wildcards
        self.on_finished = on_finished
        self.result_obj: Optional[RunResult] = None
        self.error_text: Optional[str] = None

    def _progress_cb(self, value: float, message: str) -> None:
        self.setProgress(value)
        self.progressMessage.emit(message)

    def _cancel_cb(self) -> bool:
        return self.isCanceled()

    def run(self) -> bool:
        try:
            self.result_obj = run_qaqc(
                self.tcf_path,
                run_test=self.run_test,
                tuflow_exe=self.tuflow_exe,
                wildcards=self.wildcards,
                output_format="html",
                progress_callback=self._progress_cb,
                cancel_callback=self._cancel_cb,
            )
            return not self.isCanceled()
        except Exception:
            if not self.isCanceled():
                self.error_text = traceback.format_exc()
            return False

    def finished(self, result: bool) -> None:
        if self.isCanceled():
            if self.on_finished:
                self.on_finished(None, True, None)
            return

        if not result or self.error_text:
            QgsMessageLog.logMessage(
                self.error_text or "Task failed", "TUFLOW Model Health", Qgis.Critical
            )
            if self.on_finished:
                self.on_finished(None, False, self.error_text)
            return

        if self.on_finished:
            self.on_finished(self.result_obj, False, None)


class TuflowModelHealthDockWidget(QDockWidget):
    """Dockable GUI exposing the QA/QC workflow."""

    def __init__(self, parent=None):
        super().__init__("TUFLOW Model Health QA/QC", parent)
        self.setObjectName("TuflowModelHealthDockWidget")

        self.settings = QSettings()
        self._current_task: Optional[QaqcTask] = None
        self._last_result: Optional[RunResult] = None

        self._build_ui()
        self._load_settings()

    # ---- UI construction ----
    def _build_ui(self) -> None:
        container = QWidget(self)
        layout = QVBoxLayout(container)

        layout.addWidget(self._build_paths_group())
        layout.addWidget(self._build_wildcard_group())
        layout.addWidget(self._build_options_group())
        layout.addWidget(self._build_run_group())
        layout.addWidget(self._build_results_group())

        layout.addStretch()
        self.setWidget(container)

    def _build_paths_group(self) -> QWidget:
        group = QGroupBox("Model setup")
        grid = QGridLayout(group)

        self.tcf_path_edit = QLineEdit()
        browse_tcf = QPushButton("Browse…")
        browse_tcf.clicked.connect(self._select_tcf)

        grid.addWidget(QLabel("TCF file"), 0, 0)
        grid.addWidget(self.tcf_path_edit, 0, 1)
        grid.addWidget(browse_tcf, 0, 2)

        self.output_dir_edit = QLineEdit()
        browse_out = QPushButton("Output folder…")
        browse_out.clicked.connect(self._select_output_folder)

        grid.addWidget(QLabel("Export folder"), 1, 0)
        grid.addWidget(self.output_dir_edit, 1, 1)
        grid.addWidget(browse_out, 1, 2)

        self.tcf_path_edit.textChanged.connect(self._update_wildcards_from_path)
        return group

    def _build_wildcard_group(self) -> QWidget:
        group = QGroupBox("Wildcards")
        v = QVBoxLayout(group)
        self.wildcard_table = QTableWidget(0, 2)
        self.wildcard_table.setHorizontalHeaderLabels(["Name", "Value"])
        self.wildcard_table.horizontalHeader().setStretchLastSection(True)
        self.wildcard_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.wildcard_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked
        )
        v.addWidget(QLabel("Detected from the TCF filename (editable):"))
        v.addWidget(self.wildcard_table)
        return group

    def _build_options_group(self) -> QWidget:
        group = QGroupBox("Options")
        grid = QGridLayout(group)

        self.stage_checkbox = QCheckBox("Stage 0/1: Parse control files + scan inputs")
        self.stage_checkbox.setChecked(True)
        self.stage_checkbox.setEnabled(False)

        self.run_test_checkbox = QCheckBox("Run TUFLOW test (-t)")
        self.run_test_checkbox.toggled.connect(self._toggle_tuflow_exe)

        self.tuflow_exe_edit = QLineEdit()
        self.tuflow_exe_edit.setEnabled(False)
        browse_exe = QPushButton("Browse exe…")
        browse_exe.clicked.connect(self._select_exe)
        browse_exe.setEnabled(False)
        self._browse_exe_btn = browse_exe

        grid.addWidget(self.stage_checkbox, 0, 0, 1, 3)
        grid.addWidget(self.run_test_checkbox, 1, 0, 1, 3)
        grid.addWidget(QLabel("TUFLOW exe"), 2, 0)
        grid.addWidget(self.tuflow_exe_edit, 2, 1)
        grid.addWidget(browse_exe, 2, 2)

        return group

    def _build_run_group(self) -> QWidget:
        group = QGroupBox("Execution")
        grid = QGridLayout(group)

        self.run_button = QPushButton("Run QA/QC")
        self.run_button.clicked.connect(self._start_run)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_task)

        self.progress_label = QLabel("Idle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        grid.addWidget(self.run_button, 0, 0)
        grid.addWidget(self.cancel_button, 0, 1)
        grid.addWidget(self.progress_label, 1, 0)
        grid.addWidget(self.progress_bar, 1, 1)

        return group

    def _build_results_group(self) -> QWidget:
        group = QGroupBox("Results")
        v = QVBoxLayout(group)
        self.summary_label = QLabel("No run yet.")
        v.addWidget(self.summary_label)

        self.model_tree_view = QTreeView()
        self.model_tree_view.setObjectName("model_tree_view")
        self.model_tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.model_tree_view.customContextMenuRequested.connect(
            self._show_tree_context_menu
        )
        self.model_tree_view.setHeaderHidden(False)
        self.model_tree_view.setExpandsOnDoubleClick(True)
        self.model_tree_view.doubleClicked.connect(self._on_tree_activated)
        self._set_empty_tree_model()

        v.addWidget(QLabel("Model structure:"))
        v.addWidget(self.model_tree_view)

        self.report_view = QTextBrowser()
        self.report_view.setOpenExternalLinks(True)

        export_row = QHBoxLayout()
        self.export_html_btn = QPushButton("Export HTML…")
        self.export_txt_btn = QPushButton("Export TXT…")
        self.export_json_btn = QPushButton("Export JSON…")
        for btn in (self.export_html_btn, self.export_txt_btn, self.export_json_btn):
            btn.setEnabled(False)
        self.export_html_btn.clicked.connect(self._export_html)
        self.export_txt_btn.clicked.connect(self._export_txt)
        self.export_json_btn.clicked.connect(self._export_json)

        export_row.addWidget(self.export_html_btn)
        export_row.addWidget(self.export_txt_btn)
        export_row.addWidget(self.export_json_btn)
        export_row.addStretch()

        v.addWidget(self.report_view)
        v.addLayout(export_row)
        return group

    def _set_empty_tree_model(self) -> None:
        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Name", "Type", "Exists", "Path"])
        self.model_tree_view.setModel(model)
        self.model_tree_view.setColumnHidden(3, True)

    def _build_tree_row(self, node) -> List[QStandardItem]:
        label = node.name
        if node.path and not node.exists:
            label = f"⚠️ {label} (missing)"

        name_item = QStandardItem(label)
        type_item = QStandardItem(node.category.value if node.category else "")
        exists_text = "✅" if node.exists or node.path is None else "❌"
        exists_item = QStandardItem(exists_text)
        path_item = QStandardItem(str(node.path) if node.path else "")

        for itm in (name_item, type_item, exists_item, path_item):
            itm.setEditable(False)

        tooltip_parts = []
        if node.path:
            tooltip_parts.append(str(node.path))
            name_item.setData(str(node.path), TREE_PATH_ROLE)
        if node.source_control:
            tooltip_parts.append(f"from {node.source_control}")
        if tooltip_parts:
            name_item.setToolTip(" | ".join(tooltip_parts))

        for child in node.children:
            name_item.appendRow(self._build_tree_row(child))

        return [name_item, type_item, exists_item, path_item]

    def _populate_model_tree(self, model_tree) -> None:
        if not hasattr(self, "model_tree_view"):
            return

        model = QStandardItemModel()
        model.setHorizontalHeaderLabels(["Name", "Type", "Exists", "Path"])

        root_item = model.invisibleRootItem()
        if model_tree:
            for child in model_tree.children:
                root_item.appendRow(self._build_tree_row(child))

        self.model_tree_view.setModel(model)
        self.model_tree_view.setColumnHidden(3, True)
        self.model_tree_view.expandAll()

    def _on_tree_activated(self, index) -> None:
        path = index.sibling(index.row(), 0).data(TREE_PATH_ROLE)
        if not path:
            return
        self._open_file_location(Path(path))

    def _show_tree_context_menu(self, point) -> None:
        index = self.model_tree_view.indexAt(point)
        if not index.isValid():
            return
        path = index.sibling(index.row(), 0).data(TREE_PATH_ROLE)
        if not path:
            return

        menu = QMenu(self.model_tree_view)
        action = menu.addAction("Open containing folder")
        action.triggered.connect(lambda: self._open_file_location(Path(path)))
        menu.exec_(self.model_tree_view.viewport().mapToGlobal(point))

    def _open_file_location(self, path: Path) -> None:
        target = path if path.is_dir() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ---- Settings ----
    def _load_settings(self) -> None:
        base = PLUGIN_SETTINGS_KEY
        self.tcf_path_edit.setText(self.settings.value(f"{base}/last_tcf", ""))
        self.tuflow_exe_edit.setText(self.settings.value(f"{base}/last_tuflow_exe", ""))
        self.output_dir_edit.setText(self.settings.value(f"{base}/last_output", ""))
        wildcards_json = self.settings.value(f"{base}/last_wildcards", "{}")
        try:
            self._wildcards_from_settings = json.loads(wildcards_json)
        except Exception:
            self._wildcards_from_settings = {}
        self._update_wildcards_from_path(self.tcf_path_edit.text())

    def _save_settings(self) -> None:
        base = PLUGIN_SETTINGS_KEY
        self.settings.setValue(f"{base}/last_tcf", self.tcf_path_edit.text())
        self.settings.setValue(f"{base}/last_tuflow_exe", self.tuflow_exe_edit.text())
        self.settings.setValue(f"{base}/last_output", self.output_dir_edit.text())
        self.settings.setValue(
            f"{base}/last_wildcards", json.dumps(self._collect_wildcards())
        )

    # ---- UI helpers ----
    def _select_tcf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select TCF", self.tcf_path_edit.text() or "", "TCF Files (*.tcf)"
        )
        if path:
            self.tcf_path_edit.setText(path)

    def _select_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select TUFLOW executable",
            self.tuflow_exe_edit.text() or "",
            "Executable (*.exe *.*)",
        )
        if path:
            self.tuflow_exe_edit.setText(path)

    def _select_output_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select export folder", self.output_dir_edit.text() or ""
        )
        if path:
            self.output_dir_edit.setText(path)

    def _toggle_tuflow_exe(self, checked: bool) -> None:
        self.tuflow_exe_edit.setEnabled(checked)
        self._browse_exe_btn.setEnabled(checked)

    def _update_wildcards_from_path(self, path: str) -> None:
        names = find_wildcards_in_filename(Path(path)) if path else []
        self.wildcard_table.setRowCount(0)
        remembered = getattr(self, "_wildcards_from_settings", {})
        for row, name in enumerate(names):
            self.wildcard_table.insertRow(row)
            name_item = QTableWidgetItem(name)
            name_item.setFlags(Qt.ItemIsEnabled)
            value_item = QTableWidgetItem(remembered.get(name, ""))
            self.wildcard_table.setItem(row, 0, name_item)
            self.wildcard_table.setItem(row, 1, value_item)

    def _collect_wildcards(self) -> dict:
        mapping = {}
        for row in range(self.wildcard_table.rowCount()):
            name_item = self.wildcard_table.item(row, 0)
            value_item = self.wildcard_table.item(row, 1)
            if not name_item:
                continue
            name = name_item.text().strip()
            value = value_item.text().strip() if value_item else ""
            if name:
                mapping[name] = value
        return mapping

    def _set_running(self, running: bool, message: str = "") -> None:
        self.run_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.progress_label.setText(message or ("Running" if running else "Idle"))
        if not running:
            self.progress_bar.setValue(0)

    # ---- Execution ----
    def _start_run(self) -> None:
        tcf_path = self.tcf_path_edit.text().strip()
        if not tcf_path:
            self.summary_label.setText("Please select a TCF file.")
            return

        if not tcf_path.lower().endswith(".tcf"):
            self.summary_label.setText("TCF path must end with .tcf")
            return

        wildcards = self._collect_wildcards()
        tuflow_exe = self.tuflow_exe_edit.text().strip()

        run_test = self.run_test_checkbox.isChecked()
        validation = validate_wildcards(
            tcf_path,
            wildcards,
            run_test=run_test,
            stages_enabled={"stage0_1": True, "run_test": run_test},
            will_build_paths=True,
        )

        if validation.severity == "error":
            QMessageBox.critical(self, "Missing wildcards", validation.message)
            self.summary_label.setText(validation.message)
            return
        elif validation.severity == "warning":
            self.summary_label.setText(validation.message)
            QgsMessageLog.logMessage(
                validation.message, "TUFLOW Model Health", Qgis.Warning
            )

        self._save_settings()
        self._last_result = None
        self.summary_label.setText("Running QA/QC…")
        self.report_view.clear()
        self._set_empty_tree_model()

        self._current_task = QaqcTask(
            tcf_path=tcf_path,
            run_test=run_test,
            tuflow_exe=tuflow_exe,
            wildcards=wildcards,
            on_finished=self._task_finished,
        )
        self._current_task.progressMessage.connect(self._on_progress_message)
        self._current_task.progressChanged.connect(
            lambda v: self.progress_bar.setValue(int(v))
        )
        QgsApplication.taskManager().addTask(self._current_task)
        self._set_running(True, "Started")

    def _cancel_task(self) -> None:
        if self._current_task:
            self._current_task.cancel()
            self.progress_label.setText("Cancelling…")

    def _on_progress_message(self, message: str) -> None:
        self.progress_label.setText(message)

    def _task_finished(self, result: Optional[RunResult], canceled: bool, error: Optional[str]):
        self._set_running(False, "Finished" if result else "Idle")
        self._current_task = None

        if canceled:
            self.summary_label.setText("Run cancelled.")
            return

        if error:
            self.summary_label.setText("Error during QA/QC run. See logs for details.")
            return

        if not result:
            self.summary_label.setText("Run failed.")
            return

        self._last_result = result
        self._update_results_ui(result)

    # ---- Results handling ----
    def _update_results_ui(self, result: RunResult) -> None:
        errors = sum(1 for f in result.findings if f.severity == Severity.CRITICAL)
        warnings = sum(1 for f in result.findings if f.severity == Severity.MAJOR)
        infos = sum(1 for f in result.findings if f.severity == Severity.MINOR)
        errors += len(result.inputs_missing)

        self.summary_label.setText(
            f"Errors: {errors} | Warnings: {warnings} | Info: {infos}"
        )

        self._populate_model_tree(getattr(result, "model_tree", None))

        html_report = result.report_html or render_html_report(result)
        self.report_view.setHtml(html_report)

        for btn in (self.export_html_btn, self.export_txt_btn, self.export_json_btn):
            btn.setEnabled(True)

    # ---- Export helpers ----
    def _export_html(self) -> None:
        if not self._last_result:
            return
        default_dir = self.output_dir_edit.text() or str(Path(self.tcf_path_edit.text()).parent)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export HTML", str(Path(default_dir) / "tuflow_qaqc_report.html"), "HTML (*.html)"
        )
        if path:
            content = self._last_result.report_html or render_html_report(self._last_result)
            Path(path).write_text(content, encoding="utf-8")

    def _export_txt(self) -> None:
        if not self._last_result:
            return
        default_dir = self.output_dir_edit.text() or str(Path(self.tcf_path_edit.text()).parent)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export TXT", str(Path(default_dir) / "tuflow_qaqc_report.txt"), "Text (*.txt)"
        )
        if path:
            Path(path).write_text(self._last_result.report_text, encoding="utf-8")

    def _export_json(self) -> None:
        if not self._last_result:
            return
        default_dir = self.output_dir_edit.text() or str(Path(self.tcf_path_edit.text()).parent)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON", str(Path(default_dir) / "tuflow_qaqc_report.json"), "JSON (*.json)"
        )
        if path:
            payload = {
                "ok": self._last_result.ok,
                "inputs_missing": self._last_result.inputs_missing,
                "logs_used": self._last_result.logs_used,
                "timings": self._last_result.timings,
                "findings": [
                    {
                        "id": f.id,
                        "severity": f.severity.value,
                        "category": f.category,
                        "message": f.message,
                        "suggestion": f.suggestion,
                        "file": str(f.file) if f.file else None,
                        "line": f.line,
                    }
                    for f in self._last_result.findings
                ],
                "report_text": self._last_result.report_text,
            }
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
