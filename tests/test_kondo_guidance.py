"""Alignment help uses the selected charging energies without choosing mu."""
from copy import deepcopy

import pytest

from aiida_empa_orca.kondo_data import exchange
from aiidalab_orca.kondo_guidance import charging_context, chemical_potential_help
from test_kondo import table


def test_guidance_bounds_match_exchange_and_preserve_the_table():
    source = table()
    before = deepcopy(source)
    context = charging_context(source)
    report = exchange(source, {})
    assert [-context['addition_ev'], context['removal_ev']] == report['stability_interval_ev']
    assert source == before
    assert 'outside this result’s charging range' in chemical_potential_help(context, 0.)


def test_guidance_reports_both_costs_and_open_boundaries():
    context = charging_context({'transitions': [
        {'side': 'removal', 'energy_ev': -6.}, {'side': 'addition', 'energy_ev': -1.},
        {'side': 'removal', 'energy_ev': -8.}, {'side': 'addition', 'energy_ev': 2.}]})
    text = chemical_potential_help(context, 4.)
    assert '1.000 &lt; μ &lt; 6.000' in text
    assert 'minimum removal cost <b>2.000 eV' in text
    assert 'minimum addition cost <b>3.000 eV' in text
    assert 'μ ≈ +5.3 eV' in text and '−5.3 eV' in text
    assert 'outside this result’s' not in text
    assert 'below 0.1 eV' in chemical_potential_help(context, 5.95)
    for mu in (1., 6., 7.):
        assert 'outside the allowed range' in chemical_potential_help(context, mu)
    assert 'Enter a finite' in chemical_potential_help(context, float('nan'))


@pytest.mark.parametrize('rows', [[], [{'side': 'removal', 'energy_ev': -6.}],
    [{'side': 'removal', 'energy_ev': -6.}, {'side': 'addition', 'energy_ev': float('inf')}]])
def test_incomplete_or_nonfinite_charging_data_are_not_presented_as_valid(rows):
    with pytest.raises(ValueError):
        charging_context({'transitions': rows})


def test_changing_mu_updates_help_without_setting_a_value_or_submitting(monkeypatch):
    from aiidalab_orca import kondo as ui
    monkeypatch.setattr(ui.service, 'history', lambda _: [])
    monkeypatch.setattr(ui.service, 'chemical_potential_context', lambda _: {'removal_ev': 6., 'addition_ev': -1.})
    submitted = []
    monkeypatch.setattr(ui.service, 'submit_channels', lambda _: submitted.append('channels'))
    widget = ui.KondoChannels('table', 'tools', 'cubehandler')
    try:
        assert widget.mu.value == 0. and widget.mu_help in widget.children
        assert 'outside the allowed range' in widget.mu_help.value
        widget.mu.value = 4.
        assert widget.mu.value == 4. and 'minimum removal cost <b>2.000 eV' in widget.mu_help.value
        assert widget.plan is None and widget.submit.disabled and submitted == []
    finally:
        widget.close()
