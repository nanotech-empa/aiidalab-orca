"""Convergence criteria check individual roots and require repeated refinements."""
import pytest
from aiida_empa_orca.dmrg_workchain import calibration_errors, energy_changes, stable_history, validate_plan


def point(energies):
    return {'energies_hartree': energies,
            'sweep_converged': True,
            'excitation_energies_ev': [(x-energies[0])*27.211386245988 for x in energies]}


def test_two_refinements_required():
    history = [point([-10.]), point([-10.00001]), point([-10.00002])]
    assert not stable_history(history[:2], .001)[0]
    passed, changes = stable_history(history, .001)
    assert passed and len(changes) == 2


def test_averaged_root_cancellation_cannot_certify_convergence():
    first = point([-10., -9., -8.])
    second = point([-10.01, -8.99, -8.])
    assert energy_changes(first, second)['max_root_energy_change_ev'] > .2
    assert not stable_history([first, first, second], .001)[0]


def test_gap_changes_are_checked_independently():
    first = point([-10., -9., -8.])
    second = point([-10.00003, -8.99997, -8.])
    change = energy_changes(first, second)
    assert change['max_root_energy_change_ev'] < .001
    assert change['max_gap_change_ev'] > .001


@pytest.mark.parametrize('bonds', [[128, 64], [64, 64], [0, 64], []])
def test_invalid_ladders_rejected(bonds):
    with pytest.raises(ValueError):
        validate_plan({'nroots': 1, 'validation_bonds': [64], 'target_bonds': bonds,
                       'validation_tolerance_hartree': 1e-6, 'stability_tolerance_ev': .001})


def test_valid_calibration_and_refinement_plan():
    plan = {'nroots': 3, 'validation_bonds': [256, 512], 'target_bonds': [128, 256, 512],
            'validation_tolerance_hartree': 1e-6, 'stability_tolerance_ev': .001}
    assert validate_plan(plan) == plan


def test_gap_calibration_keeps_absolute_energy_error_visible_and_bounded():
    plan = {'validation_observable': 'gaps', 'validation_tolerance_hartree': 1e-6,
            'validation_absolute_ceiling_hartree': .0001/27.211386245988}
    exact = [-10., -9., -8.]
    result = calibration_errors([-10.+3e-6, -9.+3.2e-6, -8.+3.1e-6], exact, plan)
    assert result['accepted'] and result['reference_max_energy_error_hartree'] > 1e-6
    assert result['reference_max_gap_error_hartree'] < 1e-6
    assert not calibration_errors([-9.99, -8.99, -7.99], exact, plan)['accepted']


def test_gap_validation_does_not_replace_default_energy_validation():
    result = calibration_errors([-9.999997], [-10.], {'validation_tolerance_hartree': 1e-6})
    assert not result['accepted'] and result['validation_observable'] == 'energies'


def test_bond_stability_requires_sweep_convergence_at_every_compared_m():
    p = point([-10.]); bad = dict(p, sweep_converged=False)
    assert not stable_history([p, bad, p], .001)[0]
    assert stable_history([p, p, p], .001)[0]


@pytest.mark.parametrize('phase', ['validation', 'target', 'ordering'])
def test_unconverged_sweeps_repeat_same_m_before_any_ladder_advance(monkeypatch, phase):
    from types import SimpleNamespace
    from aiida.common import AttributeDict
    from aiida_empa_orca import dmrg_workchain as module
    result = dict(point([-10.]), sweep_converged=False, hamiltonian_sha256='ham')
    node = SimpleNamespace(uuid='calc', exit_status=311,
        outputs=AttributeDict({'results': SimpleNamespace(uuid='result', get_dict=lambda: result)}))
    monkeypatch.setattr(module.orm, 'load_node', lambda u: node)
    ctx = AttributeDict(dict(phase=phase, index=1, current={'phase': phase, 'bond_dimension': 256,
        'ordering': 'fiedler', 'uuid': 'calc'}, hashes={phase: 'ham'}, trace=[], result_uuids=[],
        history=[], plan={'max_sweep_extensions': 3}))
    process = SimpleNamespace(ctx=ctx, report=lambda *a: None, clean=lambda *a: None,
        publish=lambda: None, fail=lambda *a: pytest.fail('Must continue before exhausting the extension budget'))
    module.DmrgConvergenceWorkChain.inspect_result(process)
    assert ctx.phase == phase and ctx.index == 1 and ctx.history == []
    assert ctx.sweep_parent_uuid == 'calc' and ctx.sweep_extensions == 1
    assert len(ctx.trace) == 1 and ctx.trace[0]['sweep_converged'] is False


def test_extension_budget_stops_without_increasing_m(monkeypatch):
    from types import SimpleNamespace
    from aiida.common import AttributeDict
    from aiida_empa_orca import dmrg_workchain as module
    result = dict(point([-10.]), sweep_converged=False, hamiltonian_sha256='ham')
    node = SimpleNamespace(uuid='calc', exit_status=311,
        outputs=AttributeDict({'results': SimpleNamespace(uuid='result', get_dict=lambda: result)}))
    monkeypatch.setattr(module.orm, 'load_node', lambda u: node)
    ctx = AttributeDict(dict(phase='target', index=0, sweep_extensions=3,
        current={'phase': 'target', 'bond_dimension': 2048, 'ordering': 'fiedler', 'uuid': 'calc'},
        hashes={'target': 'ham'}, trace=[], result_uuids=[], history=[], plan={'max_sweep_extensions': 3}))
    def fail(code, reason): ctx.error=code; ctx.phase='done'
    process = SimpleNamespace(ctx=ctx, report=lambda *a: None, fail=fail)
    module.DmrgConvergenceWorkChain.inspect_result(process)
    assert ctx.error == 405 and ctx.index == 0 and ctx.sweep_parent_uuid == 'calc'
