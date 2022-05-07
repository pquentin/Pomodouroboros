"""
This is a setup.py script generated by py2applet

Usage:
    python setup.py py2app
"""

from setuptools import setup

APP = ["mac/Pomodouroboros.py"]
DATA_FILES = ["IBFiles/GoalListWindow.xib"]
OPTIONS = {
    "plist": {
        "LSUIElement": True,
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleIdentifier": "im.glyph.and.this.is.pomodouroboros",
    },
    "iconfile": "icon.icns"
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
