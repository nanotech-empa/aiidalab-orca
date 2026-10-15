"""Configured ORCA helper executable, used only inside CalcJob sandboxes."""
import runpy
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('store_electronic.py', 'plot_cubes.py'):
        raise SystemExit('Usage: orca-tools {store_electronic.py|plot_cubes.py}')
    path = Path(sys.argv[1])
    if not path.is_file():
        raise SystemExit('The CalcJob input script is missing')
    runpy.run_path(str(path), run_name='__main__')
