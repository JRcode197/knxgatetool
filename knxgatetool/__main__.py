"""Start KNXGateTool as a Python module or packaged GUI executable."""
from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
from knxgatetool.ui import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KNXGateTool")
    app.setOrganizationName("KNXGateTool")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
