"""Native DMRG input, convergence classification and data-only staging."""
import io
import numpy as np
import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process
from aiida_empa_orca.dmrg import DmrgCalculation, dmrg_input, header_parameters, summarize_dmrg

HEADER = '&FCI NORB=4, NELEC=4, MS2=0, ORBSYM=1,1,1,1, ISYM=1,\n&END\n'


def settings():
    return {'nroots': 3, 'max_bond_dimension': 64, 'threads': 1,
            'memory_gb': 1, 'max_sweeps': 32, 'ordering': 'none',
            'sweep_tolerance': 1e-9, 'davidson_tolerance': 1e-10}


def test_native_input_keeps_hamiltonian_and_singlet_target():
    text = dmrg_input(header_parameters(HEADER), settings())
    assert 'spin 0\n' in text and 'nroots 3\n' in text
    assert 'integral_tol 0\nintegral_rescale none\n' in text
    assert 'noreorder\n' in text and 'twodot_to_onedot 24\n' in text
    assert '16 64 1e-10 0\n' in text and 'mps_dir mps\n' in text
    assert 'sweep_tol 0\n' in text
    assert not any(value in text for value in ['statespecific', 'orbital_rotation', 'nonspinadapted'])


@pytest.mark.parametrize('header', [HEADER.replace('MS2=0', 'MS2=2'),
                                   HEADER.replace('NELEC=4', 'NELEC=3'),
                                   HEADER.replace('ORBSYM=1,1', 'ORBSYM=1,2')])
def test_unsupported_spin_or_symmetry_fails(header):
    with pytest.raises(ValueError):
        header_parameters(header)


def test_two_site_native_switch_corner_case_is_rejected():
    with pytest.raises(ValueError, match='active space'):
        header_parameters(HEADER.replace('NORB=4', 'NORB=2'))


def test_restart_uses_existing_bond_space_and_native_checkpoint_mode():
    text = dmrg_input(header_parameters(HEADER), dict(settings(), max_bond_dimension=128), parent_bond=64)
    assert 'fullrestart\n' in text
    assert '0 64 1e-07 1e-05\n' in text
    assert '4 96 1e-08 1e-06\n' in text
    assert '8 128 1e-10 1e-06\n' in text


def test_restart_does_not_silently_shrink_the_parent_state():
    with pytest.raises(ValueError, match='parent bond'):
        dmrg_input(header_parameters(HEADER), settings(), parent_bond=128)


def test_one_root_native_stopping_is_enabled_only_after_two_site_phase():
    text = dmrg_input(header_parameters(HEADER), dict(settings(), nroots=1, max_sweeps=64))
    assert 'twodot_to_onedot 24\n' in text
    assert 'sweep_tol 1e-09\n' in text
    assert 'weights' not in text


def test_one_root_restart_has_no_multistate_weights():
    text = dmrg_input(header_parameters(HEADER), dict(settings(), nroots=1, max_bond_dimension=128), parent_bond=64)
    assert 'fullrestart\n' in text and 'weights' not in text


def test_converged_one_site_ground_state_can_finish_before_sweep_cap():
    data = list(arrays())
    data[0] = data[0][:26, :1]
    data[1:3] = [a[:26] for a in data[1:3]]
    data[3] = data[3][:1]; data[4] = data[4][:1]
    assert summarize_dmrg(*data, dict(settings(), nroots=1, max_sweeps=64), 2)['sweep_converged']


def arrays():
    energies = np.tile([-1., -.2, 2.], (32, 1))
    density = np.array([np.diag([1., 0]), np.diag([1., 0])])
    return energies, np.full(32, 64), np.full(32, 1e-8), energies[-1].copy(), [density] * 3


def test_sweep_convergence_does_not_claim_bond_convergence():
    result = summarize_dmrg(*arrays(), settings(), 2)
    assert result['sweep_converged']
    assert not result['bond_dimension_convergence_established']
    assert not result['full_CAS_computed']
    assert result['density_checks'][0]['trace'] == 2


def test_individual_roots_checked_even_if_average_does_not_change():
    data = list(arrays())
    data[0][-2] += np.array([1e-5, -1e-5, 0])
    assert not summarize_dmrg(*data, settings(), 2)['sweep_converged']


def test_incorrect_electron_count_rejected():
    with pytest.raises(ValueError, match='density'):
        summarize_dmrg(*arrays(), settings(), 4)


def test_target_bond_dimension_must_be_reached():
    data = list(arrays()); data[1][-1] = 32
    with pytest.raises(ValueError, match='dimension'):
        summarize_dmrg(*data, settings(), 2)


def test_incomplete_sweep_schedule_rejected():
    data = list(arrays())
    data[:3] = [array[:17] for array in data[:3]]
    with pytest.raises(ValueError, match='Incomplete'):
        summarize_dmrg(*data, settings(), 2)


def test_native_code_stages_only_public_input_and_integrals(aiida_profile_clean, aiida_localhost, aiida_manager):
    code = orm.InstalledCode(label='block2-staging', computer=aiida_localhost,
        filepath_executable='/verified/block2main', default_calc_job_plugin='empa_orca.dmrg').store()
    code.base.extras.set('block2', {'version': '0.5.4'})
    builder = DmrgCalculation.get_builder()
    builder.code = code
    builder.hamiltonian = orm.SinglefileData(file=io.BytesIO(HEADER.encode()), filename='native.fcidump')
    builder.settings = orm.Dict(dict=settings())
    builder.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    process = instantiate_process(aiida_manager.get_runner(), DmrgCalculation, **builder._inputs())
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        assert sorted(folder.get_content_list()) == ['dmrg-collect.sh', 'dmrg.conf', 'input-adapter.json']
        assert info.local_copy_list[0][2] == 'hamiltonian.fcidump'
        assert info.codes_info[0].cmdline_params == ['dmrg.conf']
        assert all(isinstance(item, tuple) and item[0].startswith('compact/') for item in info.retrieve_list)
        assert not any(item[0] == 'mps' or item[0].startswith('mps/') for item in info.retrieve_list)
        assert info.append_text == 'sh dmrg-collect.sh "$?"'


def test_fixed_m_continuation_keeps_one_site_checkpoint_without_noise_ramp():
    text = dmrg_input(header_parameters(HEADER), settings(), parent_bond=64, continue_sweeps=True)
    assert 'onedot\n' in text and 'fullrestart\n' in text
    assert 'twodot_to_onedot' not in text
    assert 'schedule\n0 64 1e-10 0\nend' in text
    with pytest.raises(ValueError, match='same bond dimension'):
        dmrg_input(header_parameters(HEADER), settings(), parent_bond=32, continue_sweeps=True)
    with pytest.raises(ValueError, match='checkpoint'):
        dmrg_input(header_parameters(HEADER), settings(), continue_sweeps=True)


def test_one_site_continuation_can_converge_after_two_additional_sweeps():
    data = list(arrays()); data[:3] = [x[:2] for x in data[:3]]
    data[0] = data[0][:, :1]; data[3] = data[3][:1]; data[4] = data[4][:1]
    r = summarize_dmrg(*data, dict(settings(), nroots=1), 2, continue_sweeps=True)
    assert r['sweep_converged'] and r['fixed_m_sweep_continuation']
    assert r['two_site_to_one_site_at_sweep'] is None and r['last_two_site_discarded_weights'] == []
    data[1][0] = 32
    with pytest.raises(ValueError, match='dimension'):
        summarize_dmrg(*data, dict(settings(), nroots=1), 2, continue_sweeps=True)
