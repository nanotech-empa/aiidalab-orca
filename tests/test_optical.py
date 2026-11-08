"""Native manual benchmark, state identity, scientific failure gates and UI safety."""

from pathlib import Path

import ipywidgets as ipw
import pytest

from aiida_empa_orca import optical
from aiida_empa_orca.protocols import protocol_settings

FIXTURES = Path(__file__).parent / 'fixtures' / 'optical'


def electronic():
    return protocol_settings('pbe-v1', {'basis': 'def2-SVP', 'charge': 0, 'multiplicity': 1})


def native(name='pyridine-tda'):
    return (FIXTURES / (name+'.out')).read_text()


def result(name='pyridine-tda', **values):
    return optical.parse_result(native(name), electronic(), {'nto_states': [1, 2, 3], **values}, expected_electrons=42)


def test_pyridine_reproduces_the_published_manual_reference():
    # ORCA 6.1 manual, section 5.6.11, same input and published geometry.
    data = result()
    rows = data['states']
    assert [row['energy_ev'] for row in rows[:3]] == pytest.approx([4.294795, 4.325874, 5.442702], abs=1e-6)
    assert [row['oscillator_strength'] for row in rows[:3]] == pytest.approx([0, .003830922, .019114326], abs=1e-8)
    assert rows[2]['nto']['pairs'][0]['weight'] == pytest.approx(.63243468, abs=1e-8)
    assert rows[2]['nto']['pairs'][1]['weight'] == pytest.approx(.36314467, abs=1e-8)
    assert rows[0]['contributions'][0]['particle'] == 22
    assert rows[0]['nto']['pairs'][0]['particle'] == 21  # Different orbital bases.
    assert not data['dyson_compatible'] and not data['provides_casci_vectors']


def test_ground_energy_is_not_the_native_excited_final_energy():
    data = result()
    assert data['ground_energy_hartree'] == pytest.approx(-247.79114598098997)
    assert data['ground_energy_hartree'] != pytest.approx(-247.633315175813)
    optical.parse_result(native(), electronic(), {'nto_states': [1, 2, 3]}, expected_energy=data['ground_energy_hartree'])
    with pytest.raises(ValueError, match='changed energy'):
        optical.parse_result(native(), electronic(), {'nto_states': [1, 2, 3]}, expected_energy=-247.633315175813)


def test_full_tddft_preserves_nonprobability_nto_weights_and_response_contributions():
    data = result('pyridine-full', method='TDDFT')
    assert data['states'][0]['nto']['pairs'][0]['weight'] > 1
    assert data['states'][0]['contributions'][0]['native_weight'] == .995699
    assert data['states'][0]['contributions'][0]['coefficient'] is None
    assert data['states'][0]['nto']['printed_weight_sum'] > 1


def test_triplet_global_indices_map_to_family_roots_and_dark_states_are_retained():
    data = result('pyridine-triplets', triplets=True)
    triplets = [row for row in data['states'] if row['family'] == 'triplet']
    assert [row['root'] for row in triplets] == [1, 2, 3, 4, 5]
    assert [row['native_state_index'] for row in triplets] == [6, 7, 8, 9, 10]
    assert all(row['oscillator_strength'] == 0 and row['nto'] is None for row in triplets)
    assert len(data['states']) == 10


@pytest.mark.parametrize('before,after', [
    ('ORCA TERMINATED NORMALLY', ''),
    ('SCF CONVERGED AFTER', 'SCF NOT CONVERGED AFTER'),
    ('CONVERGENCE OF RESIDUAL NORM REACHED', 'NO CONVERGENCE'),
    ('0.000000068510', '0.001000068510'),
    ('Tamm-Dancoff approximation     ... operative', 'Tamm-Dancoff approximation     ... deactivated'),
    ('STATE  5:', 'STATE  4:'),
    ('4.294795   34639.9', '4.394795   34639.9'),
    ('aiida.s2.nto', '../other.s2.nto'),
    ('0.003830923', '-0.003830923'),
    ('<S**2> =   0.000000 Mult 1', '<S**2> =   0.000000 Mult 1\npoorly normalized'),
])
def test_native_failures_and_misassigned_results_are_rejected(before, after):
    with pytest.raises(ValueError):
        optical.parse_result(native().replace(before, after), electronic(), {'nto_states': [1, 2, 3]}, expected_electrons=42)


def test_input_keeps_the_dft_reference_and_owns_only_its_response_controls():
    text = optical.optical_input(electronic(), {'method': 'TDDFT', 'nroots': 7, 'nto_states': [2, 4]})
    assert 'TDA False' in text and 'NRoots 7' in text and 'NTOStates 2,4' in text
    assert 'MOREAD' in text and '%moinp "reference.gbw"' in text
    assert all(word not in text for word in ('NoIter', 'CASSCF', 'PTMethod'))
    with pytest.raises(ValueError, match='HF'):
        optical.settings({}, electronic() | {'method': 'HF'})
    with pytest.raises(ValueError, match='RKS singlet'):
        optical.settings({'triplets': True}, electronic() | {'multiplicity': 2})
    with pytest.raises(ValueError, match='not qualified'):
        optical.settings({'triplets': True, 'nto_family': 'triplet'}, electronic())
    with pytest.raises(ValueError):
        optical.settings({'nto_states': [0]}, electronic())


def test_nto_selection_generates_complete_pairs_and_rejects_unavailable_states():
    data = result('pyridine-triplets', triplets=True)
    state, orbitals = optical.nto_selection(data, {'state_id': 'singlet:3', 'pairs': [1, 2]})
    assert orbitals == [[0, 19], [0, 20], [0, 21], [0, 22]]
    with pytest.raises(ValueError, match='No qualified NTO'):
        optical.nto_selection(data, {'state_id': 'triplet:1', 'pairs': [1]})
    with pytest.raises(ValueError):
        optical.nto_selection(data, {'state_id': 'singlet:1', 'pairs': [999]})


def test_clickable_spectrum_and_dark_state_selection_submit_nothing():
    from aiidalab_orca.optical import OpticalSpectrum
    chosen = []
    viewer = OpticalSpectrum(result('pyridine-triplets', triplets=True), chosen.append)
    try:
        viewer._action({'action': 'select', 'ids': ['triplet:2']})
        assert viewer.state.value == 'triplet:2' and chosen[-1] == 'triplet:2'
        assert 'data-ids' in viewer.chart.value and 'Oscillator strength' in viewer.chart.value
        viewer.unit.value = 'nm'
        assert 'Wavelength (nm)' in viewer.chart.value
        viewer._action({'action': 'select', 'ids': ['not-a-state']})
        assert viewer.state.value == 'triplet:2'
    finally:
        viewer.close()


def test_optical_workspace_does_not_prepare_cas_or_submit_on_navigation(monkeypatch):
    from aiidalab_orca import viewer, optical as ui, casci
    from aiidalab_orca.app import close_widget_tree
    from test_result_navigation import reference_data
    monkeypatch.setattr(viewer, 'molecule', lambda *a: ipw.Label('Geometry'))
    monkeypatch.setattr(ui.service, 'defaults', lambda *a: {'nprocs': 1, 'memory_mb': 1024, 'wallclock_seconds': 600})
    monkeypatch.setattr(ui.service, 'runs', lambda *a: [])
    def unwanted(*args, **kwargs):
        raise AssertionError('Opening optical analysis must not construct CASCI or submit')
    monkeypatch.setattr(casci, 'CasciStates', unwanted)
    monkeypatch.setattr(ui.service, 'submit', unwanted)
    page = viewer.show_result(reference_data())
    try:
        panel = page.open_analysis('optical')
        assert isinstance(panel, ui.OpticalExcitations)
        assert panel.plan is None and panel.submit.disabled
        panel.plan = {'reviewed': True}
        panel.submit.disabled = False
        panel.method.value = 'TDDFT'
        assert panel.plan is None and panel.submit.disabled
        assert 'states' not in page.tabs.panels
    finally:
        close_widget_tree(page)


def test_nto_preview_driver_preserves_pair_identity_and_spin(tmp_path, monkeypatch):
    import json
    import numpy as np
    from ase import Atoms
    from ase.io.cube import write_cube
    from aiida_empa_orca.scripts import plot_cubes
    monkeypatch.chdir(tmp_path)
    (tmp_path/'aiida.gbw').write_bytes(b'nto')
    identity = {'kind': 'NTO', 'state_id': 'uks:1', 'pairs': [1, 2], 'excitations_uuid': 'immutable-source'}
    request = {'files': [{'name': 'aiida.gbw', 'size_bytes': 3}], 'plot_executable': 'plot',
        'cubehandler_executable': 'cubehandler', 'orbital_identity': identity,
        'parameters': {'orbitals': [[0, 2], [0, 3], [1, 2], [1, 3]], 'spin_density': False,
                       'grid_points': 40, 'retention': 'leave'}}
    (tmp_path/'request.json').write_text(json.dumps(request))
    atoms = Atoms('H', positions=[[1, 1, 1]], cell=[5, 5, 5])
    def execute(args, **kwargs):
        if args[0] == 'plot':
            commands = kwargs['input'].splitlines()
            index, spin = int(commands[3]), int(commands[5])
            with open(f'aiida.mo{index}{"ab"[spin]}.cube', 'w') as handle:
                write_cube(handle, atoms, data=np.ones((10, 10, 10))*.2)
        else:
            assert '--no-low-precision' in args
            (tmp_path/'previews').mkdir()
            for cube in (tmp_path/'full_cubes').glob('*.cube'):
                with open(tmp_path/'previews'/cube.name, 'w') as handle:
                    write_cube(handle, atoms, data=np.ones((3, 3, 3))*.2)
    monkeypatch.setattr(plot_cubes.subprocess, 'run', execute)
    plot_cubes.main()
    manifest = json.loads((tmp_path/'manifest.json').read_text())
    assert manifest['orbital_source'] == identity
    assert {row['filename'] for row in manifest['cubes']} == {'nto_a_0002.cube', 'nto_a_0003.cube', 'nto_b_0002.cube', 'nto_b_0003.cube'}
    assert all(row['orbital_type'] == 'NTO' and 'occupation' not in row for row in manifest['cubes'])
    assert len(list((tmp_path/'full_cubes').glob('*.cube'))) == 4
    assert not (tmp_path/'aiida.gbw').exists()  # Expendable stage, not the source NTO.


def test_open_shell_response_preserves_spin_channels_and_mixed_spin_diagnostics():
    electronic_uks = electronic() | {'multiplicity': 2}
    data = optical.parse_result(native('allyl-uks'), electronic_uks, {'nto_states': [1, 2, 3]}, expected_electrons=23)
    assert {r['family'] for r in data['states']} == {'uks'}
    assert all(r['multiplicity'] is None and r['spin_squared'] is not None for r in data['states'])
    pairs = data['states'][0]['nto']['pairs']
    assert {r['hole_spin'] for r in pairs} == {'a', 'b'}
    assert pairs[0]['weight'] != pytest.approx(next(r['weight'] for r in pairs if r['hole_spin'] == 'b'))
    state, orbitals = optical.nto_selection(data, {'state_id': 'uks:1', 'pairs': [1, 8]})
    assert orbitals == [[0, 11], [0, 12], [1, 10], [1, 11]]


def test_reopening_saved_ntos_selects_a_member_and_switching_state_clears_it(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from aiida import orm
    from aiidalab_orca import optical as ui
    table = result()
    node = SimpleNamespace(uuid='saved-cubes', is_finished_ok=True, ctime=datetime.now(timezone.utc),
        inputs=SimpleNamespace(selection=SimpleNamespace(get_dict=lambda: {'state_id': 'singlet:3', 'pairs': [1]})),
        outputs=SimpleNamespace(manifest=SimpleNamespace(get_dict=lambda: {'cubes': [
            {'filename': 'nto_a_0020.cube', 'spin': 0, 'index': 20},
            {'filename': 'nto_a_0021.cube', 'spin': 0, 'index': 21}]})))
    monkeypatch.setattr(orm, 'load_node', lambda _: node)
    monkeypatch.setattr(ui.service, 'result', lambda _: table)
    monkeypatch.setattr(ui.service, 'cube_defaults', lambda _: {'storage_policy': {'stash_directory': '/tmp/nto', 'threshold_mb': 100},
        'codes': {'plot': [('plot', 'plot-id')], 'cubehandler': [('cubehandler', 'cube-id')]}})
    monkeypatch.setattr(ui.service, 'cube_runs', lambda _: ['saved-cubes'])
    shown = []
    monkeypatch.setattr(ui.NtoPreviews, '_show_cube', lambda self, *_: shown.append(self.cube.value) if self.cube.value else None)
    viewer = ui.NtoPreviews('optical-id')
    try:
        viewer.choose('singlet:3')
        assert viewer.previous.value == 'saved-cubes'
        assert viewer.cube.value == 'nto_a_0020.cube'
        assert shown[-1] == 'nto_a_0020.cube'
        viewer.choose('singlet:2')
        assert viewer.previous.value is None and viewer.cube.value is None
    finally:
        viewer.close()
