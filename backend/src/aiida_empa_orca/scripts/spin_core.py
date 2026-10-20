"""Spin-resolved core identification for light elements and one all-electron Co.

The deliberately narrow shell count is checked against the native energy gap
and atomic populations. Co 2s/2p must never be mistaken for ligand 1s orbitals.
"""
import math


def spin_assignments(text, numbers, *, original=None):
    from pathlib import Path
    from runpy import run_path

    # The CalcJob stages both scripts; its runtime need not install the plugin.
    shared = run_path(str(Path(__file__).with_name('core_orbitals.py')))
    levels, populations = shared['levels'], shared['populations']
    if ('ORCA TERMINATED NORMALLY' not in text or 'Using GuessMode=CMatrix' in text
            or 'Input Geometry matches current geometry' not in text
            or 'Input basis set matches current basis set' not in text):
        raise ValueError('Core inspection must preserve the supplied geometry, basis and individual MOs')
    channels, tables = levels(text), populations(text, len(numbers))
    if len(channels) not in (1, 2) or len(tables) != len(channels):
        raise ValueError('Missing spin-resolved core populations')
    if numbers.count(27) > 1 or set(numbers)-{1, 6, 7, 8, 9, 27}:
        raise ValueError('Core identification supports light elements and at most one Co')
    heavy = [i for i, z in enumerate(numbers) if z != 1]
    cobalt = [i for i, z in enumerate(numbers) if z == 27]
    count = len(heavy)+4*len(cobalt)
    rows, groups = [], []
    for spin, channel in enumerate(channels):
        core = channel[:count]
        occupied = 1 if len(channels) == 2 else 2
        if (len(core) != count or any(abs(c['occupation']-occupied) > 1e-6 for c in core)
                or (original is None and (any(c['energy_hartree'] >= -5 for c in core)
                    or len(channel) <= count or channel[count]['energy_hartree'] <= -5))):
            raise ValueError('The expected light-element/Co inner-core subspace is not separated from valence')
        original_rows = {r['index']: r for r in original or [] if r['spin'] == spin}
        co_rows, ligand_rows = [], []
        for orbital in core:
            values = tables[spin][orbital['index']]
            if not all(math.isfinite(v) and 0 <= v <= 1.001 for v in values) or abs(sum(values)-1) > .01:
                raise ValueError('Incomplete or invalid native core populations')
            atom = max(range(len(values)), key=values.__getitem__)
            row = orbital | {'spin': spin, 'spin_channel': 'alpha' if spin == 0 else 'beta',
                'atom_index': atom, 'population': values[atom], 'atomic_populations': values}
            if original is not None:
                if orbital['index'] not in original_rows:
                    raise ValueError('Core orbital ordering changed during localization')
                row['energy_hartree'] = None
                is_co = original_rows[orbital['index']]['shell'] != '1s' or original_rows[orbital['index']]['atom_index'] in cobalt
            else:
                is_co = bool(cobalt and sum(values[i] for i in cobalt) >= .9)
            (co_rows if is_co else ligand_rows).append(row)
        if len(co_rows) != 5*len(cobalt):
            raise ValueError('Co 1s/2s/2p shell count is ambiguous')
        for index, row in enumerate(co_rows):
            row['shell'] = '1s' if index == 0 else '2s' if index == 1 else '2p'
        for row in ligand_rows:
            row['shell'] = '1s'
        if ligand_rows:
            indices = [r['index'] for r in ligand_rows]
            if indices != list(range(min(indices), max(indices)+1)):
                raise ValueError('Ligand 1s localization window is not contiguous')
            groups.append({'spin': spin, 'first': min(indices), 'last': max(indices)})
        rows.extend(co_rows+ligand_rows)
    verified = True
    for spin in range(len(channels)):
        one_s = [r for r in rows if r['spin'] == spin and r['shell'] == '1s']
        verified &= ({r['atom_index'] for r in one_s} == set(heavy) and len(one_s) == len(heavy))
    verified &= all(r['population'] >= .95 for r in rows)
    return rows, bool(verified), groups


def prepare_spin_core(request, text):
    """Localize occupied ligand cores separately in each spin channel."""
    import json
    import shutil
    import subprocess
    from pathlib import Path
    rows, verified, groups = spin_assignments(text, request['numbers'])
    original = rows
    localized = not verified
    if localized:
        source = 'reference.gbw'
        localizer = Path(request['orca']).with_name('orca_loc')
        for sequence, group in enumerate(groups):
            target = f'localized_{sequence}.gbw'
            filename = f'localize_{sequence}.inp'
            Path(filename).write_text('\n'.join([source, target, str(group['first']), str(group['last']),
                '1', str(group['spin']), '128', '1e-8', '0', '.95', '.85', '2', '1', '0'])+'\n')
            with Path('localize.log').open('a') as handle:
                subprocess.run([str(localizer), filename], stdout=handle, stderr=subprocess.STDOUT, check=True)
            source = target
        shutil.copyfile(source, 'localized.gbw')
        with Path('localized.out').open('w') as handle:
            subprocess.run([request['orca'], 'localized_check.inp'], stdout=handle, stderr=subprocess.STDOUT, check=True)
        rows, verified, _ = spin_assignments(Path('localized.out').read_text(), request['numbers'], original=original)
        if not verified:
            raise ValueError('Spin-resolved core assignment remains ambiguous after occupied-core localization')
        shutil.copyfile('localized.gbw', 'aiida.gbw')
    report = {'schema_version': 2, 'method': 'spin_core_only_pipek_mezey' if localized else 'spin_canonical',
        'population_method': 'ORCA Loewdin atomic populations per MO', 'minimum_population': .95,
        'assignments': rows, 'original_assignments': original, 'filename': 'aiida.gbw'}
    Path('core.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(report, allow_nan=False))
