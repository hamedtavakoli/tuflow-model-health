import sys
from pathlib import Path


def _ensure_core_on_path() -> None:
    """Make sure the tuflow_qaqc package bundled with the plugin is importable."""

    plugin_dir = Path(__file__).resolve().parent
    candidates = [plugin_dir, plugin_dir.parent]
    for candidate in candidates:
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


_ensure_core_on_path()


def classFactory(iface):
    from .main import TuflowModelHealthPlugin

    return TuflowModelHealthPlugin(iface)
