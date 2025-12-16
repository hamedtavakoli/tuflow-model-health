import importlib.util
from pathlib import Path


try:
    _qgis_spec = importlib.util.find_spec("qgis.core")
except ModuleNotFoundError:
    _qgis_spec = None
if _qgis_spec:
    from qgis.core import QgsMessageLog, Qgis
else:
    QgsMessageLog = None
    Qgis = None


def _log_bundled_engine_path() -> None:
    """Log which tuflow_qaqc module is in use to detect conflicts."""

    from .vendor import tuflow_qaqc as bundled_qaqc

    engine_path = Path(bundled_qaqc.__file__).resolve()
    plugin_root = Path(__file__).resolve().parent
    in_plugin = plugin_root in engine_path.parents or engine_path.parent == plugin_root
    if QgsMessageLog and Qgis:
        level = Qgis.Info if in_plugin else Qgis.Warning
        prefix = "Using bundled" if in_plugin else "Unexpected"
        QgsMessageLog.logMessage(
            f"{prefix} tuflow_qaqc at {engine_path}", "TUFLOW Model Health", level
        )


def classFactory(iface):
    _log_bundled_engine_path()

    from .main import TuflowModelHealthPlugin

    return TuflowModelHealthPlugin(iface)
