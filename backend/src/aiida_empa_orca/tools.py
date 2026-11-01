"""Configured ORCA helper executable, used only inside CalcJob sandboxes."""
import runpy
import sys
from pathlib import Path


def main():
    names = ('store_electronic.py', 'plot_cubes.py', 'compact_orbitals.py', 'core_orbitals.py', 'xps_finalize.py')
    if len(sys.argv) != 2 or sys.argv[1] not in names:
        raise SystemExit('Usage: orca-tools {'+'|'.join(names)+'}')
    path = Path(sys.argv[1])
    if not path.is_file():
        raise SystemExit('The CalcJob input script is missing')
    runpy.run_path(str(path), run_name='__main__')
