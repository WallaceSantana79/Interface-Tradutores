from PyInstaller import log as logging

logger = logging.getLogger(__name__)


def pre_find_module_path(hook_api):
    # Override PyInstaller default behavior that excludes tkinter when Tcl/Tk
    # auto-detection fails on some Windows PythonManager installs.
    logger.info("Using project override for tkinter pre-find hook.")
