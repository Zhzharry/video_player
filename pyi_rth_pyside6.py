# PyInstaller runtime hook — runs before main script; complements _fix_frozen_qt_paths() in main.py
import os
import sys


def _apply():
    if not getattr(sys, "frozen", False):
        return
    root = getattr(sys, "_MEIPASS", None)
    if not root:
        root = os.path.dirname(sys.executable)
    root = os.path.normpath(root)

    extra = [root, os.path.join(root, "PySide6")]
    pside = os.path.join(root, "PySide6")
    if os.path.isdir(pside):
        for rel in (("Qt6", "bin"), ("Qt", "bin"), ("lib", "bin")):
            d = os.path.join(pside, *rel)
            if os.path.isdir(d):
                extra.append(d)
    sh = os.path.join(root, "shiboken6")
    if os.path.isdir(sh):
        extra.append(sh)

    seen: set[str] = set()
    if hasattr(os, "add_dll_directory"):
        for d in extra:
            d = os.path.normpath(d)
            if d in seen or not os.path.isdir(d):
                continue
            seen.add(d)
            try:
                os.add_dll_directory(d)
            except OSError:
                pass

    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")

    for rel in (("PySide6", "plugins"), ("PySide6", "Qt6", "plugins")):
        qtp = os.path.join(root, *rel)
        if os.path.isdir(qtp):
            os.environ["QT_PLUGIN_PATH"] = qtp
            plat = os.path.join(qtp, "platforms")
            if os.path.isdir(plat):
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plat
            break


_apply()
