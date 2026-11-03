"""Read the recorded CoPc energy-only RASSCF/readback validation contract.

This reader does not accept new wavefunctions or generate a spectrum. Native
physical checks belong to the linked validators, whose captured sources and
completed calculation provenance must remain available.
"""
import hashlib
import math
import re

import numpy as np
from aiida import orm
from aiida_empa_orca.cobalt_xps import HARTREE_TO_EV

from .property_services import source_node

EXPECTED = {3: 270, 1: 210}


def _finite(value):
    if not math.isfinite(value):
        raise ValueError('Nonfinite multireference energy-check evidence')
    return value


def _states(rows):
    table = {(r['multiplicity'], r['root']): _finite(r['energy_hartree']) for r in rows}
    expected = {(m, i) for m, count in EXPECTED.items() for i in range(count)}
    if len(rows) != len(table) or set(table) != expected:
        raise ValueError('The complete reviewed 480-state manifold is missing or duplicated')
    return table


def _mean(table):
    return .5 * sum(sum(table[m, i] for i in range(count)) / count
                    for m, count in EXPECTED.items())


def _close(a, b, tolerance=1e-8):
    if abs(_finite(a) - _finite(b)) > tolerance:
        raise ValueError('The multireference summary differs from its linked evidence')


def _function(node):
    if not isinstance(node, orm.CalcFunctionNode) or not node.is_finished_ok:
        raise ValueError('Missing completed multireference validation')


def _native(stdout, *, optimized=False):
    job = stdout.creator
    if not isinstance(job, orm.CalcJobNode) or not job.is_finished_ok:
        raise ValueError('A native multireference calculation did not finish successfully')
    text = stdout.get_content()
    if ('ORCA TERMINATED NORMALLY' not in text or 'CI-PROBLEM SOLVED' not in text
            or 'POORLY NORMALIZED MO DETECTED' in text
            or 'CI-ITERATIONS NOT CONVERGED' in ' '.join(text.upper().split())):
        raise ValueError('Native termination, normalization or CI checks failed')
    if optimized:
        if ('THE CAS-SCF GRADIENT HAS CONVERGED' not in text
                or 'THE CAS-SCF ENERGY   HAS CONVERGED' not in text
                or not re.search(r'^\s*--- Orbital Update\s*\[', text, re.M)):
            raise ValueError('Native orbital optimization did not converge')
    elif re.search(r'^\s*--- Orbital Update\s*\[', text, re.M):
        raise ValueError('The independent readback performed orbital optimization')
    markers = list(re.finditer(
        r'CAS-SCF STATES FOR BLOCK\s+\d+\s+MULT=\s*(\d+)\s+NROOTS=\s*(\d+)', text))
    states = {}
    for i, marker in enumerate(markers):
        mult, count = map(int, marker.groups())
        fragment = text[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)]
        fragment = fragment.split('LOEWDIN ORBITAL-COMPOSITIONS', 1)[0]
        found = re.findall(r'ROOT\s+(\d+)\s*:\s*E=\s*([-+\d.Ee]+)\s+Eh', fragment)
        if (len(found) != count or {int(r) for r, _ in found} != set(range(count))
                or EXPECTED.get(mult) != count):
            raise ValueError('Native state table is incomplete or incompatible')
        states.update({(mult, int(root)): _finite(float(energy)) for root, energy in found})
    if set(states) != {(m, i) for m, count in EXPECTED.items() for i in range(count)}:
        raise ValueError('Missing native multireference states')
    return job, states, text


def _orbitals(rows, assignment):
    if set(rows) != {str(i) for i in range(138, 147)}:
        raise ValueError('Missing reviewed CoPc core/valence orbital evidence')
    core = [rows[str(i)] for i in range(138, 141)]
    if any(_finite(r['co_p']) < .95 or _finite(r['energy_hartree']) >= -5 for r in core):
        raise ValueError('The deep Co 2p identity was not retained')
    _close(sum(_finite(r['occupation']) for r in core), 5, 1e-3)
    _close(sum(_finite(rows[str(i)]['occupation']) for i in range(141, 147)), 9, 1e-3)
    pi = assignment['ligand_pi']
    d = assignment['co_d']
    if (len(d) != 5 or set([pi, *d]) != set(range(141, 147))
            or _finite(rows[str(pi)]['ligand_pz']) < .75
            or any(_finite(rows[str(i)]['co_d']) < .55 for i in d)):
        raise ValueError('The reviewed ligand-pi/five-d valence block was not retained')


def validated_record(data):
    """Expose a completed energy diagnostic, never an unvalidated restart."""
    record = data.get_dict()
    acceptance = data.creator
    _function(acceptance)
    if (record.get('accepted_as_energy_benchmark') is not True
            or record.get('accepted_as_multiplet_spectrum') is not False
            or record.get('accepted_as_relaxed_xps') is not False):
        raise ValueError('This record is not an accepted energy-only benchmark')
    validation = acceptance.inputs.relaxed_validation
    _function(validation.creator)
    relaxed = validation.get_dict()
    if (not relaxed.get('native_orbital_optimization_validated')
            or any(record.get(k) != v for k, v in relaxed.items())):
        raise ValueError('The relaxed optimization evidence changed or is incomplete')
    frozen_node = acceptance.inputs.frozen_control
    _function(frozen_node.creator)
    frozen = frozen_node.get_dict()
    if (not frozen.get('frozen_controls_passed')
            or _finite(frozen['maximum_neutral_restart_difference_hartree']) > 1e-7):
        raise ValueError('The original frozen neutral/core controls did not pass')
    optimizer, optimized_states, optimizer_text = _native(validation.creator.inputs.stdout, optimized=True)
    readback, readback_states, _ = _native(acceptance.inputs.stdout)
    if (str(readback.inputs.nodes.source.uuid) != str(optimizer.outputs.remote_folder.uuid)
            or str(readback.inputs.nodes.validation.uuid) != str(validation.uuid)):
        raise ValueError('Readback does not use the validated optimized checkpoint')
    model_uuid = str(acceptance.inputs.model.uuid)
    if any(str(n.uuid) != model_uuid for n in (
            validation.creator.inputs.model, frozen_node.creator.inputs.model,
            optimizer.inputs.nodes.model, readback.inputs.nodes.model)):
        raise ValueError('The model differs between frozen, relaxed and readback stages')
    for key, function, source_key in (
            ('validator_sha256', validation.creator, 'validator_source'),
            ('readback_validator_sha256', acceptance, 'validator_source'),
            ('control_validator_sha256', acceptance, 'control_validator_source')):
        actual = hashlib.sha256(function.inputs[source_key].get_content().encode()).hexdigest()
        if record.get(key) != actual:
            raise ValueError('The captured multireference validator differs from its record')
    gradients = re.findall(r'\|\|g\|\|\s*=\s*([-+\d.Ee]+)', optimizer_text)
    if not gradients:
        raise ValueError('Missing final native orbital gradient')
    _close(record['final_orbital_gradient'], float(gradients[-1]), 1e-12)
    if (not 0 <= _finite(record['final_orbital_gradient']) <= 2.5e-4
            or abs(_finite(record['initial_seed_energy_difference_hartree'])) > 1e-7
            or not 0 <= _finite(record['maximum_state_readback_difference_hartree']) <= 1e-7):
        raise ValueError('The orbital-gradient or saved-wavefunction tolerance failed')
    if record['numerical'] != frozen['core_numerical']:
        raise ValueError('The generated integration grids changed')
    original, final = _states(frozen['core_states']), _states(record['states'])
    if final != optimized_states:
        raise ValueError('The accepted state energies differ from native optimization output')
    maximum_difference = max(abs(readback_states[key] - final[key]) for key in final)
    _close(record['maximum_state_readback_difference_hartree'], maximum_difference, 1e-12)
    if maximum_difference > 1e-7:
        raise ValueError('At least one native state failed saved-wavefunction readback')
    _close(record['frozen_state_average_energy_hartree'], _mean(original))
    _close(record['state_average_energy_hartree'], _mean(final))
    _close(record['state_average_relaxation_hartree'], _mean(final) - _mean(original))
    _close(record['readback_state_average_energy_hartree'], _mean(final), 1e-7)
    neutral = frozen['neutral_reference_energy_hartree']
    _close(record['neutral_reference_energy_hartree'], neutral)
    binding = record['spin_free_ionization_energies_hartree']
    if _states(binding) != final:
        raise ValueError('Ionization energies do not describe the validated states')
    for row in binding:
        _close(row['binding_energy_hartree'], row['energy_hartree'] - neutral)
    _orbitals(record['target_orbitals'], record['valence_assignment'])
    _orbitals(record['readback_target_orbitals'], record['valence_assignment'])
    structure = frozen_node.creator.inputs.structure
    reference = frozen_node.creator.inputs.source_reference
    _close(reference.get_dict()['ground_energy_hartree'], neutral, 1e-7)
    minima = [dict(multiplicity=m,
                   frozen_binding_energy_ev=(min(original[m, i] for i in range(count)) - neutral) * HARTREE_TO_EV,
                   relaxed_binding_energy_ev=(min(final[m, i] for i in range(count)) - neutral) * HARTREE_TO_EV)
              for m, count in EXPECTED.items()]
    return record | {
        'data_uuid': str(data.uuid), 'validation_uuid': str(acceptance.uuid),
        'structure_uuid': str(structure.uuid), 'reference_uuid': str(reference.uuid),
        'optimization_calcjob_uuid': str(optimizer.uuid), 'readback_calcjob_uuid': str(readback.uuid),
        'model': acceptance.inputs.model.get_dict(), 'lowest_spin_free_energies': minima,
        'state_average_lowering_ev': -record['state_average_relaxation_hartree'] * HARTREE_TO_EV}


def records(source_uuid):
    """Discover only completed diagnostics at the selected neutral geometry."""
    source = source_node(source_uuid)
    settings, atoms = source.inputs.settings.get_dict(), source.outputs.structure.get_ase()
    if settings['charge'] != 0 or settings['multiplicity'] != 2:
        return {'records': [], 'diagnostics': []}
    uuids = orm.QueryBuilder().append(orm.Dict, filters={
        'attributes.accepted_as_energy_benchmark': True,
        'attributes.accepted_as_multiplet_spectrum': False,
        'attributes.accepted_as_relaxed_xps': False,
        'attributes.native_orbital_optimization_validated': True}, tag='data', project='uuid').append(
            orm.CalcFunctionNode, with_outgoing='data',
            filters={'attributes.process_state': 'finished', 'attributes.exit_status': 0}).all(flat=True)
    rows, diagnostics = [], []
    for uuid in uuids:
        node = orm.load_node(uuid)
        try:
            other = node.creator.inputs.frozen_control.creator.inputs.structure.get_ase()
            if (other.get_chemical_symbols() != atoms.get_chemical_symbols()
                    or not np.allclose(other.positions - other.positions[0], atoms.positions - atoms.positions[0],
                                       atol=1e-5, rtol=0)):
                continue
            rows.append(validated_record(node))
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            diagnostics.append(f'{uuid}: {exc}')
    return {'records': rows, 'diagnostics': diagnostics}
