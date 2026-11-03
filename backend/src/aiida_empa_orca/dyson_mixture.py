"""Incoherent mixtures of saved Dyson results, retaining actual initial energies."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from aiida import engine, orm

from .dyson_data import IDENTITY

MIXTURE_PROCESS = 'aiida_empa_orca.dyson_mixture.combine_dyson'
NATIVE_PROCESS = 'aiida.calculations:empa_orca.dyson'


def mix_tables(tables, populations):
    if len(tables) < 2 or set(tables) != set(populations):
        raise ValueError('Choose at least two Dyson results and one population for each')
    if any(type(p) not in (int,float) or not math.isfinite(p) or not 0 <= p <= 1 for p in populations.values()):
        raise ValueError('Initial populations must be finite numbers between zero and one')
    if not math.isclose(sum(populations.values()), 1., abs_tol=1e-12, rel_tol=0):
        raise ValueError('Initial populations must sum to one; they are not silently normalized')
    first = next(iter(tables.values()))
    initial_states, transitions, seen = [], [], set()
    for key, table in tables.items():
        if table.get('strength_convention') != 'highest_ms_component':
            raise ValueError('Use raw single-initial-state Dyson results, before spin/population weighting')
        if (table['orbital_reference_uuid'] != first['orbital_reference_uuid'] or
                table['active_space'] != first['active_space'] or
                table['initial_state']['charge'] != first['initial_state']['charge']):
            raise ValueError('Mixtures must share charge, common spatial orbitals and active space')
        identity = tuple(table['initial_state'][k] for k in ('charge','multiplicity','root'))
        if identity in seen:
            raise ValueError('Choose one complete Dyson result per initial state, not overlapping pilot/full results')
        seen.add(identity)
        initial_states.append(dict(table['initial_state'], state_uuid=table['initial_state_uuid'],
                                   source=key,population=populations[key]))
        for row in table['transitions']:
            transitions.append(dict(deepcopy(row), id=key+'__'+row['id'],source=key,
                source_transition_id=row['id'],initial_state_uuid=table['initial_state_uuid'],
                initial_multiplicity=table['initial_state']['multiplicity'],
                initial_root=table['initial_state']['root'],
                initial_energy_hartree=table['initial_state']['energy_hartree'],
                population=populations[key]))
    result = deepcopy(first)
    result.update(schema_version=2, initial_states=initial_states, initial_state_uuid=None,
        initial_state=dict(charge=first['initial_state']['charge'],multiplicity=None,root=None,energy_hartree=None),
        transitions=sorted(transitions,key=lambda r:r['energy_ev']),
        strength_convention='initial_state_mixture',
        energy_convention='Actual transition energy for each initial state; no degeneracy approximation',
        populations=dict(populations))
    return result


def cube_source(transitions):
    producer = transitions.creator
    if producer is None or not producer.is_finished_ok:
        raise ValueError('Select successful Dyson transitions')
    if producer.process_type == NATIVE_PROCESS:
        return dict(coefficients_uuid=str(producer.outputs.retrieved.uuid),
                    artifact_uuid=str(producer.inputs.artifacts.initial.uuid),native_uuid=str(producer.uuid))
    if producer.process_type == MIXTURE_PROCESS:
        key = next(iter(producer.inputs.parameters.get_dict()))
        result = cube_source(producer.inputs[key])
        result['coefficients_uuid'] = str(producer.outputs.retrieved.uuid)
        return result
    raise ValueError('Select a native Dyson result or an explicit population mixture')


def checked_sources(sources, populations):
    tables = {key:node.get_dict() for key,node in sources.items()}
    result = mix_tables(tables,populations)
    identities = []
    for key,node in sources.items():
        if node.creator is None or node.creator.process_type != NATIVE_PROCESS or not node.creator.is_finished_ok:
            raise ValueError('Population mixtures require completed native Dyson tables')
        state = orm.load_node(tables[key]['initial_state_uuid']).get_dict()
        identities.append({k:state[k] for k in IDENTITY})
    if any(identity != identities[0] for identity in identities[1:]):
        raise ValueError('Initial states must share geometry, integral model and fixed-orbital CASCI identity')
    return result


@engine.calcfunction
def combine_dyson(parameters, **sources):
    """Create new immutable mixture data; never renormalize orbitals or shift poles."""
    populations = parameters.get_dict()
    table = checked_sources(sources,populations)
    arrays = {}
    shape = None
    for key,node in sources.items():
        with node.creator.outputs.retrieved.base.repository.open('coefficients.npz',mode='rb') as handle:
            with np.load(handle,allow_pickle=False) as archive:
                for row in node.get_dict()['transitions']:
                    coefficients = archive[row['id']]
                    shape = coefficients.shape if shape is None else shape
                    if coefficients.ndim != 1 or coefficients.shape != shape or not np.isfinite(coefficients).all():
                        raise ValueError('Dyson components do not share one finite AO coefficient basis')
                    arrays[key+'__'+row['id']] = coefficients.copy()
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        np.savez_compressed(path/'coefficients.npz',**arrays)
        (path/'transitions.json').write_text(json.dumps(table,indent=2,allow_nan=False))
        retrieved = orm.FolderData(tree=directory)
    return dict(transitions=orm.Dict(dict=table),retrieved=retrieved)
