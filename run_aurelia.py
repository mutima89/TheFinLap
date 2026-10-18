"""Launcher used by PyInstaller and for running from source: python run_aurelia.py"""
import sys

from aurelia.app import main

if __name__ == "__main__":
    sys.exit(main())
