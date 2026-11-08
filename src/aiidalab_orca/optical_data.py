"""Plain-data presentation and downloads for stored optical results."""

import base64
import csv
import html
import io
import json


def pair_members(state, number, cubes):
    """Identify both native pair members within one cube manifest."""
    pair = state['nto']['pairs'][number-1]
    result = {}
    for role in ('hole', 'particle'):
        matches = [c['filename'] for c in cubes
                   if c['spin'] == (0 if pair[role+'_spin'] == 'a' else 1) and c['index'] == pair[role]]
        if len(matches) != 1:
            return {}
        result[role] = matches[0]
    return result


def availability(data, inventory):
    result = {r['id']: {k: set() for k in ('ready', 'running', 'failed', 'missing')} for r in data['states']}
    for run in inventory:
        if run['state_id'] not in result:
            continue
        row = result[run['state_id']]
        if run['success']:
            row['ready'].update(run['ready_pairs'])
            row['missing'].update(set(run['pairs'])-set(run['ready_pairs']))
        else:
            row['failed' if run['finished'] else 'running'].update(run['pairs'])
    for row in result.values():
        row['missing'] -= row['ready']
        row['failed'] -= row['ready'] | row['running']
    return {key: {kind: sorted(values) for kind, values in row.items()} for key, row in result.items()}


def preview_label(row):
    parts = []
    for kind, label in [('ready', 'Ready'), ('running', 'Running'), ('failed', 'Failed'), ('missing', 'Files unavailable')]:
        if row.get(kind):
            parts.append(label + ': ' + ', '.join(map(str, row[kind])))
    return '; '.join(parts) or 'Not generated'


def metadata(data):
    electronic = data.get('electronic_settings', {})
    return {'optical_calculation_uuid': data.get('uuid', ''), 'excitations_uuid': data.get('excitations_uuid', ''),
            'geometry_uuid': data.get('structure_uuid', ''), 'source_retrieved_uuid': data.get('source_retrieved_uuid', ''),
            'response_method': data['method'], 'functional': electronic.get('method', ''),
            'basis': electronic.get('basis', ''), 'reference_type': data.get('reference_type', ''),
            'reference_charge': data.get('reference_charge', ''),
            'reference_multiplicity': data.get('reference_multiplicity', ''),
            'ground_energy_hartree': data.get('ground_energy_hartree', ''),
            'oscillator_convention': data.get('oscillator_convention', 'native electric-dipole length gauge; no SOC')}


def csv_text(rows):
    handle = io.StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def states_csv(data, previews=None):
    context = metadata(data)
    rows = []
    for state in data['states']:
        nto = state['nto'] or {}
        rows.append(context | {key: state.get(key, '') for key in
            ('id', 'family', 'root', 'native_state_index', 'energy_ev', 'wavelength_nm', 'oscillator_strength',
             'spin_squared', 'multiplicity', 'native_multiplicity_label')} |
            {'nto_analysis_available': bool(nto), 'printed_nto_pairs': len(nto.get('pairs', [])),
             'native_nto_weight_sum': nto.get('printed_weight_sum', ''),
             'cube_preview_pairs': json.dumps((previews or {}).get(state['id'], {}).get('ready', []))})
    return csv_text(rows)


def spectrum_csv(data, x, energies, curve, view):
    context = metadata(data) | view
    return csv_text([context | {'display_coordinate': float(position), 'energy_ev': float(energy),
        'broadened_oscillator_strength_per_ev': float(value)} for position, energy, value in zip(x, energies, curve)])


def download_link(name, label, content, mime):
    encoded = base64.b64encode(content.encode()).decode()
    return f'<a download="{html.escape(name)}" href="data:{mime};base64,{encoded}">{html.escape(label)}</a>'
