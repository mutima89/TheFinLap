# PyInstaller spec for Aurelia Finance Lab (one-folder Windows build).
# Build from the project root:  pyinstaller --clean --noconfirm packaging/aurelia.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from aurelia import __version__  # noqa: E402

# Pages are imported lazily with importlib, so PyInstaller cannot see them on its own.
hidden = collect_submodules("aurelia")

# Qt modules the app never uses; excluding them keeps the build smaller.
qt_unused = ["Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender", "QtBluetooth",
             "QtCharts", "QtDataVisualization", "QtGraphs", "QtHttpServer", "QtLocation", "QtMultimedia",
             "QtMultimediaWidgets", "QtNetworkAuth", "QtNfc", "QtPositioning", "QtQuick3D", "QtRemoteObjects",
             "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort", "QtSpatialAudio", "QtTextToSpeech",
             "QtWebChannel", "QtWebEngineCore", "QtWebEngineQuick", "QtWebEngineWidgets", "QtWebSockets",
             "QtWebView", "QtQuick", "QtQml", "QtQuickWidgets", "QtPdf", "QtPdfWidgets", "QtDesigner", "QtHelp",
             "QtUiTools", "QtSql", "QtTest", "QtOpenGLWidgets", "QtSvgWidgets"]
excludes = ["tkinter", "pytest", "pytestqt", "IPython", "notebook", "scipy"] + [f"PySide6.{m}" for m in qt_unused]

a = Analysis(
    [str(ROOT / "run_aurelia.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "aurelia" / "assets"), "aurelia/assets")],
    hiddenimports=hidden + ["matplotlib.backends.backend_qtagg"],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
win = sys.platform.startswith("win")
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aurelia_Finance_Lab",
    console=False,
    icon=str(ROOT / "aurelia" / "assets" / "aurelia.ico"),
    version=str(ROOT / "packaging" / "version_info.txt") if win else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Aurelia_Finance_Lab", upx=False)
