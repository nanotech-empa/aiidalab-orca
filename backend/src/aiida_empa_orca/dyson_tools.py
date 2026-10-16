"""Remote executable: all Dyson work runs inside submitted CalcJobs."""
import os
import runpy
import sys
from pathlib import Path


def main():
    names = ('export_dyson.py','compute_dyson.py','dyson_cubes.py')
    if len(sys.argv) != 2 or sys.argv[1] not in names or not Path(sys.argv[1]).is_file():
        raise SystemExit('Usage: orca-dyson {'+'|'.join(names)+'}')
    os.environ.setdefault('OMP_NUM_THREADS','1')
    os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
    runpy.run_path(sys.argv[1],run_name='__main__')
