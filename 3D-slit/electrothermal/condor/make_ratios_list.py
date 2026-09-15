#!/usr/bin/env python3
"""
make_ratios_list.py -- generates the ratio,label pairs sweep.sub's
`queue ratio,label from ratios.txt` reads, using run_transient.py's own
sanitize_label() so Condor job labels always match what run_transient.py
would derive itself. Avoids hand-typing labels that could silently drift
out of sync with the naming convention used everywhere else in this repo.

Usage:
  python3 make_ratios_list.py 0.5 0.7 0.8 0.9 0.925 0.95 0.99 1.0 1.1 > ratios.txt
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_transient as rt

for arg in sys.argv[1:]:
    ratio = float(arg)
    print(f"{ratio},{rt.sanitize_label(ratio)}")
