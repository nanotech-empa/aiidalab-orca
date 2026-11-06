"""Read independently validated scalar Co diagnostics as operation-local data."""
import math

import numpy as np
from aiida import orm

from .property_services import source_node

SCHEMA = 'orca_scalar_core_relaxation_v1'


def validated_record(data):
    """Check the linked acceptance evidence before displaying a diagnostic."""
    record = data.get_dict()
    creator = data.creator
    if (record.get('schema') != SCHEMA or not record.get('accepted_as_scalar_benchmark') or
            not isinstance(creator, orm.CalcFunctionNode) or not creator.is_finished_ok):
        raise ValueError('Missing completed scalar benchmark validation')
    structure = creator.inputs.structure
    if str(structure.uuid) != record['structure_uuid']:
        raise ValueError('The benchmark geometry differs from its provenance')
    frozen, relaxed, readback = (creator.inputs[key].get_dict() for key in ('frozen', 'relaxed', 'readback'))
    electrons = int(structure.get_ase().numbers.sum()) - 1
    expected_counts = [(electrons + 2) / 2, (electrons - 2) / 2]
    for key, values in zip(('frozen', 'relaxed', 'readback'), (frozen, relaxed, readback)):
        request = values['request']
        if (request['reference_uuid'] != record['reference_uuid'] or
                request['spin_channel'] != 'beta' or request['orbital_index'] != 2 or
                str(creator.inputs[key].creator.inputs.structure.uuid) != str(structure.uuid)):
            raise ValueError('The core component/reference or geometry changed')
        core = values['core_p_orbitals']
        if (len(core) != 3 or sum(row['occupation'] < .01 for row in core) != 1 or
                any(not math.isfinite(row['co_p_population']) or not math.isfinite(row['energy_hartree']) or
                    row['co_p_population'] < .95 or row['energy_hartree'] >= -5 for row in core)):
            raise ValueError('The Co2p vacancy was not verified')
        if values['final_electron_counts'] != expected_counts:
            raise ValueError('The core-ionized electron count changed')
    audit = creator.inputs.readback_audit.get_dict()
    audit_job = creator.inputs.readback_audit.creator
    gradient = creator.inputs.gradient.get_dict()
    final_gradient = gradient.get('maximum_orbital_gradient', gradient.get('final_orbital_gradient'))
    difference = readback['energy_hartree'] - relaxed['energy_hartree']
    if (not relaxed.get('converged') or not audit.get('basic_readback_passed') or
            not isinstance(audit_job, orm.CalcJobNode) or not audit_job.is_finished_ok or
            frozen.get('orbital_optimization_performed') is not False or
            readback.get('orbital_optimization_performed') is not False or
            audit.get('orbital_optimization_performed') is not False or
            audit.get('normalization_warnings', True) or final_gradient is None or
            not math.isfinite(final_gradient) or final_gradient > 1e-6 or
            not math.isfinite(difference) or not math.isfinite(readback['spin_squared']) or
            not math.isfinite(relaxed['spin_squared']) or abs(difference) > 1e-7 or
            abs(readback['spin_squared'] - relaxed['spin_squared']) > 1e-5):
        raise ValueError('Native convergence or saved-wavefunction checks failed')
    expected = {'frozen_binding_energy_ev': frozen['binding_energy_ev'],
                'relaxed_binding_energy_ev': relaxed['binding_energy_ev'],
                'core_relaxation_lowering_ev': frozen['binding_energy_ev'] - relaxed['binding_energy_ev'],
                'final_gradient': final_gradient, 'final_spin_squared': relaxed['spin_squared'],
                'readback_energy_difference_hartree': difference}
    if any(not math.isfinite(record[key]) or not math.isfinite(value) or abs(record[key] - value) > 1e-8
           for key, value in expected.items()):
        raise ValueError('The benchmark summary differs from its acceptance evidence')
    qe = list(creator.inputs.qe_binding_energies.get_dict()['Co']['2p'].values())
    if (len(qe) != 1 or not math.isfinite(record['qe_scalar_binding_energy_ev']) or not math.isfinite(qe[0]['energy']) or
            abs(record['qe_scalar_binding_energy_ev'] - qe[0]['energy']) > 1e-8):
        raise ValueError('Missing finite QE comparison energy')
    return record | {'data_uuid': str(data.uuid),
                     'validation_uuid': str(creator.uuid),
                     'readback_calcjob_uuid': str(creator.inputs.readback_audit.creator.uuid)}


def records(source_uuid):
    """Match geometry and neutral spin; the diagnostic retains its own model."""
    source = source_node(source_uuid)
    settings = source.inputs.settings.get_dict()
    atoms = source.outputs.structure.get_ase()
    if settings['charge'] != 0 or settings['multiplicity'] != 2 or list(atoms.numbers).count(27) != 1:
        return {'records': [], 'diagnostics': []}
    uuids = orm.QueryBuilder().append(orm.Dict, filters={
        'attributes.schema': SCHEMA, 'attributes.accepted_as_scalar_benchmark': True},
        tag='data', project=['uuid']).append(orm.CalcFunctionNode, with_outgoing='data',
        filters={'attributes.process_state': 'finished', 'attributes.exit_status': 0}).all(flat=True)
    rows, diagnostics = [], []
    for uuid in uuids:
        node = orm.load_node(uuid)
        try:
            other = node.creator.inputs.structure.get_ase()
            if (other.get_chemical_symbols() != atoms.get_chemical_symbols() or
                    not np.allclose(other.positions - other.positions[0], atoms.positions - atoms.positions[0],
                                    atol=1e-5, rtol=0)):
                continue
            rows.append(validated_record(node))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            diagnostics.append(f'{uuid}: {exc}')
    return {'records': rows, 'diagnostics': diagnostics}
