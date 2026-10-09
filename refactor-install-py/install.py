#!/usr/bin/env python3
"""Entrypoint for the shared Quadlet installer."""

import sys

if sys.version_info < (3, 11):
    sys.exit("[ERROR] Bộ cài cần Python 3.11 trở lên.")

from installer.cli import main

if __name__ == "__main__":
    sys.exit(main())
