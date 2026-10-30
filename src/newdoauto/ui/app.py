"""
Application launcher for the NewDoAuto PySide6 Desktop UI.
"""

from __future__ import annotations
import sys
from typing import Optional

from PySide6.QtWidgets import QApplication

from newdoauto.ui.main_window import MainWindow


def launch_desktop_app(argv: Optional[list[str]] = None) -> int:
    """Initializes QApplication, shows MainWindow, and runs the Qt event loop."""
    app_args = argv if argv is not None else sys.argv
    app = QApplication.instance() or QApplication(app_args)
    app.setApplicationName("NewDoAuto")
    app.setOrganizationName("NewDoAuto")

    window = MainWindow()
    window.show()
    return int(app.exec())


def main() -> int:
    return launch_desktop_app()


if __name__ == "__main__":
    sys.exit(main())

