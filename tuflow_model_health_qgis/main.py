"""QGIS plugin entry point for the TUFLOW Model Health QA/QC dock widget."""

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis

from .dockwidget import TuflowModelHealthDockWidget


class TuflowModelHealthPlugin:
    """Adds a dockable QA/QC panel to QGIS."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self):
        self.action = QAction(
            QIcon(), "TUFLOW Model Health QA/QC", self.iface.mainWindow()
        )
        self.action.setToolTip("Open the TUFLOW QA/QC panel")
        self.action.triggered.connect(self.show_dock)
        self.iface.addPluginToMenu("&TUFLOW Model Health", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action:
            self.iface.removePluginMenu("&TUFLOW Model Health", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def show_dock(self):
        if not self.dock:
            self.dock = TuflowModelHealthDockWidget(self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()
        self.dock.activateWindow()
