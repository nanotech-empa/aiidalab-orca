"""Native ORCA population inspection and core-only localization in a CalcJob.

The final implementation parses native Löwdin MO populations, not squared AO
coefficients in a nonorthogonal basis. No ground-state SCF is repeated here.
"""

import json
import math
import re
import shutil
import subprocess
from pathlib import Path


def populations(text, natoms, method='LOEWDIN'):
    """Parse native percent populations, with an independent table per spin."""
    sections = text.split(method+' ATOM POPULATIONS PER MO')[1:]
    if not sections:
        raise ValueError(f'The native {method} atomic populations per MO are missing')
    tables = []
    for section in sections:
        table, columns = {}, None
        for line in section.splitlines():
            if line.strip() == 'SPIN DOWN':
                if not table:
                    raise ValueError('Missing spin-up population table')
                tables.append(table)
                table, columns = {}, None
                continue
            fields = line.split()
            if fields and all(re.fullmatch(r'\d+', x) for x in fields):
                columns = [int(x) for x in fields]
                for index in columns:
                    table[index] = [0.] * natoms
            match = re.fullmatch(r'\s*(\d+)\s+([A-Z][a-z]?)\s+(.+)', line)
            if match and columns:
                atom, _, values = match.groups()
                numbers = [float(x) for x in values.split()]
                if len(numbers) != len(columns) or int(atom) >= natoms:
                    raise ValueError('Invalid Löwdin population dimensions')
                for index, value in zip(columns, numbers):
                    table[index][int(atom)] = value / 100.
            if table and ('POPULATION ANALYSIS' in line or 'TIMINGS' in line or 'SCF properties' in line):
                break
        if not table:
            raise ValueError('Empty Löwdin population table')
        tables.append(table)
    return tables


def levels(text):
    table = text.rsplit('ORBITAL ENERGIES', 1)[-1]
    result = [[]]
    for line in table.splitlines():
        if 'SPIN DOWN ORBITALS' in line:
            result.append([])
        match = re.fullmatch(r'\s*(\d+)\s+([\d.]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*', line)
        if match:
            index, occupation, energy, _ = match.groups()
            result[-1].append({'index': int(index), 'occupation': float(occupation), 'energy_hartree': float(energy)})
        elif result[0] and 'POPULATION ANALYSIS' in line:
            break
    if not result[0] or any(not c for c in result):
        raise ValueError('Missing orbital energies or occupations')
    return result


def assignments(text, numbers, *, localized=False):
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('ORCA did not terminate normally')
    if ('Input Geometry matches current geometry' not in text or
            'Input basis set matches current basis set' not in text or
            'Guess MOs are being read from file:' not in text):
        raise ValueError('The supplied orbitals were not read at matching geometry and basis')
    if 'Using GuessMode=CMatrix' in text:
        raise ValueError('CMatrix projects the occupied subspace and changes individual core orbitals; atom assignment cannot be preserved')
    channels = levels(text)
    if len(channels) != 1:
        raise ValueError('Core preparation requires a restricted reference')
    heavy = [i for i, z in enumerate(numbers) if z != 1]
    core = channels[0][:len(heavy)]
    if (len(core) != len(heavy) or any(c['occupation'] != 2 for c in core) or
            (not localized and (any(c['energy_hartree'] >= -5 for c in core) or
                                 channels[0][len(heavy)]['energy_hartree'] <= -5))):
        raise ValueError('The occupied 1s core subspace is not separated from the valence orbitals')
    pops = populations(text, len(numbers))[0]
    rows = []
    for orbital in core:
        values = pops[orbital['index']]
        atom = max(range(len(values)), key=values.__getitem__)
        if not all(math.isfinite(x) and 0 <= x <= 1.001 for x in values) or abs(sum(values)-1) > .01:
            raise ValueError('Incomplete or invalid core populations')
        rows.append(orbital | {'energy_hartree': None if localized else orbital['energy_hartree'],
                              'atom_index': atom, 'population': values[atom], 'atomic_populations': values})
    unique = len({row['atom_index'] for row in rows}) == len(heavy)
    verified = unique and all(row['atom_index'] in heavy and row['population'] >= .95 for row in rows)
    return rows, verified


def main():
    request = json.loads(Path('request.json').read_text())
    text = Path('aiida.out').read_text()
    if request.get('kind') == 'native_casscf_co':
        import runpy
        runpy.run_path('casscf_core.py')['main'](request, text)
        return
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('ORCA did not terminate normally during core preparation; inspect aiida.out')
    if 'MaxIter==0 has been chosen - skipping the SCF' not in text:
        raise ValueError('Unexpected SCF optimization during core preparation')
    if request.get('schema_version') == 2:
        import runpy
        runpy.run_path('spin_core.py')['prepare_spin_core'](request, text)
        return
    rows, verified = assignments(text, request['numbers'])
    localized = not verified
    if localized:
        # Rotate only the fully occupied 1s subspace, preserving the closed-shell
        # determinant/density. Never mix occupied and virtual orbitals.
        localizer = Path(request['orca']).with_name('orca_loc')
        Path('localize.inp').write_text('\n'.join([
            'reference.gbw', 'localized.gbw', '0', str(len(rows)-1),
            '1', '0', '128', '1e-8', '0.0', '.95', '.85', '2', '1', '0',
        ]) + '\n')
        with Path('localize.log').open('w') as handle:
            subprocess.run([str(localizer), 'localize.inp'], stdout=handle, stderr=subprocess.STDOUT, check=True)
        with Path('localized.out').open('w') as handle:
            subprocess.run([request['orca'], 'localized_check.inp'], stdout=handle, stderr=subprocess.STDOUT, check=True)
        rows, verified = assignments(Path('localized.out').read_text(), request['numbers'], localized=True)
        if not verified:
            raise ValueError('Core orbitals remain ambiguous after core-only localization; inspect before ionization')
        # The matched-basis NoIter read must preserve the localized MO ordering.
        shutil.copyfile('localized.gbw', 'aiida.gbw')
    report = {'schema_version': 1, 'method': 'core_only_pipek_mezey' if localized else 'canonical',
              'population_method': 'ORCA Loewdin atomic populations per MO',
              'minimum_population': .95, 'assignments': rows, 'filename': 'aiida.gbw'}
    Path('core.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(report, allow_nan=False))


if __name__ == '__main__':
    main()
