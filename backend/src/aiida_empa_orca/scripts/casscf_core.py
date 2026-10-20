"""Standard-library-only Co core assignment from native CASSCF populations.

Read the unchanged internal orbitals; never load, localize or rewrite a GBW.
The producing CASSCF calculation is independently validated by the CalcJob.
"""
import hashlib
import json
import math
import re
from pathlib import Path


def core_reference(text, numbers, source_uuid):
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('The source CASSCF calculation did not terminate normally')
    cobalt = [i for i, z in enumerate(numbers) if z == 27]
    if len(cobalt) != 1:
        raise ValueError('Native Co core assignment requires exactly one cobalt atom')
    atom = cobalt[0]
    marker = 'LOEWDIN ORBITAL-COMPOSITIONS'
    if marker not in text:
        raise ValueError('Missing native CASSCF orbital-composition table')
    section = text.rsplit(marker, 1)[1].split('LOEWDIN REDUCED ACTIVE MOs')[0]
    table, columns, headers = {}, [], []
    for line in section.splitlines():
        if re.fullmatch(r'\s*\d+(?:\s+\d+)+\s*', line):
            columns = [int(x) for x in line.split()]
            if any(i in table for i in columns):
                raise ValueError('Duplicate native orbital columns')
            table.update({i: {'co_s': 0., 'co_p': 0.} for i in columns})
            headers = []
            continue
        if columns and len(headers) < 2:
            fields = line.split()
            if not fields:
                continue
            try:
                values = [float(x) for x in fields]
            except ValueError as exc:
                raise ValueError('Missing native orbital energies or occupations') from exc
            if len(values) != len(columns) or not all(math.isfinite(x) for x in values):
                raise ValueError('Invalid native orbital energies or occupations')
            key = 'energy_hartree' if not headers else 'occupation'
            for index, value in zip(columns, values):
                table[index][key] = value
            headers.append(key)
            continue
        match = re.fullmatch(r'\s*(\d+)\s+(Co|C|N|H)\s+(\S+)\s+(.+)', line)
        if not match or not columns:
            continue
        index, symbol, angular, fields = match.groups()
        values = [float(x)/100 for x in fields.split()]
        if (len(values) != len(columns) or not all(math.isfinite(x) and 0 <= x <= 1.001 for x in values)
                or not 0 <= int(index) < len(numbers) or (symbol == 'Co') != (int(index) == atom)):
            raise ValueError('Invalid native atom/orbital populations')
        if int(index) == atom and (angular == 's' or angular in ('px', 'py', 'pz')):
            key = 'co_s' if angular == 's' else 'co_p'
            for index, value in zip(columns, values):
                table[index][key] += value
    if not table or any('occupation' not in row for row in table.values()):
        raise ValueError('Incomplete native orbital-composition table')
    deep = {i: row for i, row in table.items() if row['energy_hartree'] < -5}
    s = sorted((i for i, row in deep.items() if row['co_s'] >= .95), key=lambda i: deep[i]['energy_hartree'])
    p = sorted(i for i, row in deep.items() if row['co_p'] >= .95)
    if len(s) != 2 or len(p) != 3 or len(set(s+p)) != 5:
        raise ValueError('Expected two Co s-core orbitals and three unambiguous Co 2p orbitals')
    if deep[s[0]]['energy_hartree'] >= min(deep[i]['energy_hartree'] for i in s[1:]+p):
        raise ValueError('The Co 1s orbital is not separated below the Co 2s/2p shell')
    rows = []
    for i, shell, key in [(s[0], '1s', 'co_s')]+[(i, '2p', 'co_p') for i in p]:
        row = deep[i]
        if row['occupation'] != 2 or row[key] > 1.01:
            raise ValueError('Co core orbitals must be fully occupied with valid native populations')
        rows.append({'index': i, 'shell': shell, 'atom_index': atom, 'spin': 0,
                     'occupation': row['occupation'], 'energy_hartree': row['energy_hartree'],
                     'population': row[key]})
    return {'schema_version': 1, 'method': 'native_casscf_unchanged_internal_orbitals',
            'population_method': 'ORCA Loewdin orbital compositions', 'minimum_population': .95,
            'assignments': rows, 'source_calculation_uuid': str(source_uuid),
            'source_output_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'wavefunction_modified': False}


def main(request, text):
    report = core_reference(text, request['numbers'], request['source_calculation_uuid'])
    Path('core.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(report, allow_nan=False))
