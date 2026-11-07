"""Register an immutable, single-purpose CalcJob helper; no Python selector in the GUI."""
import argparse
import hashlib
from pathlib import Path
import sys

from aiida import load_profile, orm

BODY = '''import os
import runpy
import sys
from pathlib import Path
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
if sys.argv[1:] != ["orbital_character.py"] or not Path("orbital_character.py").is_file():
    raise SystemExit("Usage: orca-character orbital_character.py")
runpy.run_path("orbital_character.py", run_name="__main__")
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--computer', default='localhost')
    parser.add_argument('--directory', type=Path, default=Path.home() / 'opt')
    args = parser.parse_args()
    if args.computer != 'localhost':
        raise SystemExit('Deploy the same wrapper with a qualified NumPy runtime on the remote computer; do not guess its Python path')
    import numpy  # The existing environment must already supply the required runtime.
    executable = '#!' + sys.executable + '\n' + BODY
    digest = hashlib.sha256(executable.encode()).hexdigest()
    destination = args.directory / ('orbital-character-' + digest[:12])
    destination.mkdir(exist_ok=True)
    path = destination / 'orca-character'
    if path.exists() and path.read_text() != executable:
        raise RuntimeError('Never overwrite an immutable worker')
    if not path.exists():
        path.write_text(executable)
        path.chmod(0o755)
    load_profile('default')
    computer = orm.load_computer(args.computer)
    label = 'orbital-character-' + digest[:12]
    matches = orm.QueryBuilder().append(orm.InstalledCode, filters={'label': label}, project='uuid').all(flat=True)
    if matches:
        code = orm.load_code(matches[0])
        if code.computer.uuid != computer.uuid or str(code.filepath_executable) != str(path):
            raise RuntimeError('The registered worker identity differs')
    else:
        code = orm.InstalledCode(label=label, computer=computer, filepath_executable=str(path),
                                 default_calc_job_plugin='empa_orca.orbital_character').store()
        code.base.extras.set_many({'aiidalab_orca_role': 'orbital_character',
                                   'wrapper_sha256': digest, 'numpy_version': numpy.__version__})
    print(f'{code.label}@{computer.label}: {code.uuid}')


if __name__ == '__main__':
    main()
