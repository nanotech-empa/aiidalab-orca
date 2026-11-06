"""Stop invalid preparation; polish and audit a core hole inside its CalcJob."""
import json
from pathlib import Path
import runpy
import subprocess


def main():
    request = json.loads(Path('xps_request.json').read_text())
    helpers = runpy.run_path(str(Path(__file__).with_name('xps_validation.py')))
    preparation = Path('preparation.out').read_text()
    # Failed, collapsed or unconstrained states never reach the polishing step.
    helpers['validate_stage'](preparation, request, 'preparation')
    for name in ('aiida', 'wavefunction_check'):
        with Path(name+'.out').open('w') as stdout:
            subprocess.run([request['orca_executable'], name+'.inp'], stdout=stdout,
                           stderr=subprocess.STDOUT, check=True)
        if name == 'aiida':
            helpers['validate_stage'](Path('aiida.out').read_text(), request, 'refinement')
    result = helpers['validate_bundle'](preparation, Path('aiida.out').read_text(),
                                       Path('wavefunction_check.out').read_text(), request)
    Path('xps_validation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
