"""GUI round-trip of saved CI controls and explicit review before submission."""
import pytest

from aiida_empa_orca import casci as backend
from aiidalab_orca import casci
from test_casci import reference_data


@pytest.fixture
def panel(monkeypatch):
    ref = reference_data()
    monkeypatch.setattr(casci.service,'reference_runs',lambda _: [
        {'uuid':'common','reference_uuid':'orbitals','kind':'QRO'}])
    monkeypatch.setattr(casci.service,'reference_data',lambda _:ref)
    monkeypatch.setattr(casci.service,'runs',lambda _:[])
    monkeypatch.setattr(casci.service,'results',lambda *args:[])
    monkeypatch.setattr(casci.service,'progress',lambda _:dict(
        state='finished',message='',finished=True,success=True))
    def review(reference, electrons, norb, values, force):
        space = {'electrons':electrons,'orbitals':list(range(6,6+norb))}
        settings = backend.casci_settings(values,ref,space)
        return dict(action='compute',settings=settings,input=backend.casci_input(ref,space,settings))
    monkeypatch.setattr(casci.service,'prepare_casci',review)
    widget = casci.CasciStates(dict(uuid='source',settings=ref['settings']))
    yield widget
    widget.close()


@pytest.mark.parametrize('controls',[
    dict(ci_solver=None,ci_maxiter=None,ci_maxdim=None),
    dict(ci_solver='CSFCI',ci_maxiter=256,ci_maxdim=10),
])
def test_saved_controls_survive_open_and_review(panel,controls):
    settings = backend.casci_settings(dict(nroots=2,**controls),reference_data(),
        {'electrons':3,'orbitals':[6,7]})
    panel._runs['saved'] = dict(uuid='saved',settings=settings,
        space={'electrons':3,'orbitals':[6,7]})
    panel.previous.options = [('Saved calculation','saved')]
    panel.previous.value = 'saved'
    assert panel.ci_solver.value == controls['ci_solver']
    assert panel.ci_maxiter.value == ('' if controls['ci_maxiter'] is None else '256')
    panel._review_casci()
    assert panel.plan is not None, panel.message.value
    assert {key:panel.plan['settings'][key] for key in controls} == controls
    assert not panel.submit.disabled
    panel.ci_maxiter.value = '512'
    assert panel.plan is None and panel.submit.disabled
    panel._review_casci()
    assert panel.plan['settings']['ci_maxiter'] == 512
    assert '  MaxIter 512\n' in panel.plan['input']
    assert 'maxiter 1\n' in panel.plan['input']


@pytest.mark.parametrize('value',['0','64.5','256\nMaxIter 2'])
def test_invalid_limit_does_not_enable_submission(panel,value):
    panel.ci_maxiter.value = value
    panel._review_casci()
    assert panel.plan is None and panel.submit.disabled
    assert 'positive integer' in panel.message.value


def test_unvalidated_solver_cannot_be_submitted_from_app(panel):
    panel.ci_solver.value = 'ACCCI'
    panel._review_casci()
    assert panel.plan is None and panel.submit.disabled
    assert 'not yet validated' in panel.message.value
