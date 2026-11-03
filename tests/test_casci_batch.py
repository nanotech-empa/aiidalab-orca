"""Reviewed charge/spin products, reuse, submission and independent browsing."""

import asyncio
import math
from copy import deepcopy

import pytest

from aiida_empa_orca import casci as backend
from aiidalab_orca import casci_batch, casci_services
from test_casci import reference_data
from test_result_navigation import reference_data as result_data


@pytest.mark.parametrize('text,positive,expected', [
    ('0 +1 -1 +2 -2',False,[0,1,-1,2,-2]),
    ('0,+1,-1,+2,-2',False,[0,1,-1,2,-2]),
    ('1 2,3 4',True,[1,2,3,4]),
    ('1 1 2 +1',True,[1,2]),
])
def test_sector_list_syntax(text, positive, expected):
    assert casci_batch.parse_integer_list(text,'values',positive=positive) == expected


@pytest.mark.parametrize('text,positive', [('',False),('1.5',False),('1,,2',False),
    ('0',True),('-1',True),('1 2..3',True),('1;2',False)])
def test_bad_sector_lists_do_not_silently_change_the_request(text, positive):
    with pytest.raises(ValueError):
        casci_batch.parse_integer_list(text,'values',positive=positive)


def test_spin_multiplet_dimensions_account_for_all_determinants():
    assert [backend.spin_sector_dimension(2,2,m) for m in [1,2,3,4,5]] == [3,0,1,0,0]
    for norb in range(1,6):
        for electrons in range(2*norb+1):
            assert sum(mult*backend.spin_sector_dimension(norb,electrons,mult)
                       for mult in range(1,2*norb+2)) == math.comb(2*norb,electrons)


def test_charges_are_absolute_and_invalid_spin_pairs_remain_visible():
    ref = reference_data() | {'charge':-1}
    space,rows = casci_batch.sector_requests(ref,3,2,[-1,0,-2,1,-3],[1,2,3,4],6)
    assert space == {'electrons':3,'orbitals':[6,7]}
    valid = {(r['charge'],r['multiplicity']):r for r in rows if r['status']=='ready'}
    assert set(valid) == {(-1,2),(0,1),(0,3),(-2,1),(1,2)}
    assert valid[(-1,2)]['active_electrons']==3
    assert valid[(0,1)]['active_electrons']==2
    assert valid[(-2,1)]['active_electrons']==4
    assert valid[(0,3)]['nroots']==1 and valid[(0,3)]['requested_roots']==6
    assert 'contains 1 state' in valid[(0,3)]['reason']
    assert len(rows)==20
    assert all(r['reason'] for r in rows if r['status']=='skip')


@pytest.fixture
def batch_panel(monkeypatch):
    from aiidalab_orca.casci import CasciStates
    from aiidalab_orca.app import close_widget_tree
    ref = reference_data() | {'n_electrons':10,'source_multiplicity':1}
    monkeypatch.setattr(casci_services,'reference_runs',lambda _:[{
        'uuid':'common','reference_uuid':'orbitals','kind':'restricted'}])
    monkeypatch.setattr(casci_services,'reference_data',lambda _:deepcopy(ref))
    monkeypatch.setattr(casci_services,'execution_details',lambda _:{'code':'orca','computer':'test-computer',
        'nprocs':2,'memory_mb':2048,'wallclock_seconds':1800})
    monkeypatch.setattr(casci_services,'runs',lambda _:[])
    monkeypatch.setattr(casci_services,'results',lambda *_:[])
    monkeypatch.setattr(casci_services,'progress',lambda uuid:{'state':'finished','finished':True,
        'success':True,'message':'','reports':[]})
    prepared=[]
    def prepare(uuid,electrons,norb,values,force=False):
        space=backend.active_space({'electrons':electrons,'orbitals':[4,5]},ref)
        settings=backend.casci_settings(values,ref,space)
        plan={'reference_uuid':uuid,'active_space':space,'settings':settings,'force_recompute':force,
              'action':'compute','reuse_uuid':None,'input':backend.casci_input(ref,space,settings)}
        prepared.append(deepcopy(plan))
        return plan
    monkeypatch.setattr(casci_services,'prepare_casci',prepare)
    panel=CasciStates(result_data())
    panel.charge.value='0 +1 -1 +2 -2'
    panel.mult.value='1 2 3'
    try:
        yield panel,prepared,ref
    finally:
        close_widget_tree(panel)


def test_batch_review_precedes_submission_and_edits_invalidate_it(batch_panel,monkeypatch):
    panel,prepared,_=batch_panel
    submitted=[]
    monkeypatch.setattr(casci_services,'submit_casci',lambda plan:submitted.append(plan))
    assert not prepared and not submitted
    panel.review.click()
    assert len(prepared)==6 and not submitted
    assert '6 new calculations' in panel.batch_review.value
    assert '9 incompatible' in panel.batch_review.value
    assert not panel.submit.disabled
    panel.roots.value=2
    assert panel.plan is None and panel.submit.disabled and not panel.batch_review.value
    panel.submit.click()
    assert not submitted
    panel.charge.value='0 +'
    panel.review.click()
    assert panel.submit.disabled and panel.plan is None
    assert 'integers separated' in panel.message.value


def test_saved_charge_filter_does_not_overwrite_submission_lists(batch_panel,monkeypatch):
    panel,_,ref=batch_panel
    rows=[]
    for i,charge in enumerate([0,1]):
        rows.append({'uuid':str(i),'state':'finished','date':'2026-11-03','label':'saved',
            'space':{'electrons':2,'orbitals':[4,5]},
            'settings':backend.casci_settings({'charge':charge,'multiplicity':1 if charge==0 else 2},
                ref,{'electrons':2,'orbitals':[4,5]})})
    monkeypatch.setattr(casci_services,'runs',lambda _:deepcopy(rows))
    redraws=[]
    monkeypatch.setattr(panel,'_refresh_diagram',lambda *_:redraws.append(True))
    panel.status.value='Current calculation progress'
    panel.process_uuid='0'
    panel._refresh_runs()
    panel.result_charge.value=1
    assert panel.previous.value=='1'
    assert (panel.charge.value,panel.mult.value)==('0 +1 -1 +2 -2','1 2 3')
    assert 'charge +1' in panel.history_status.value
    assert panel.status.value=='Current calculation progress'
    assert panel.history.selected_index is None
    assert panel.history in panel.states_view.children and panel.previous not in panel.states_view.children
    assert not redraws  # History browsing preserves the diagram, its energy zero and plot limits.


def test_existing_running_sector_is_not_submitted_again(batch_panel,monkeypatch):
    panel,prepared,ref=batch_panel
    panel.charge.value='0'
    panel.mult.value='1'
    panel.review.click()
    old=prepared[-1]
    monkeypatch.setattr(casci_services,'runs',lambda _:[{'uuid':'running','state':'waiting',
        'space':old['active_space'],'settings':old['settings']}])
    plan=casci_batch.prepare_batch('common',2,2,[0],[1],old['settings'])
    assert plan['ready'] and plan['rows'][0]['status']=='running'
    assert plan['rows'][0]['uuid']=='running' and len(prepared)==1


def test_storage_failure_blocks_batch_instead_of_skipping_valid_physics(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    def missing(*args,**kwargs):raise OSError('saved wavefunction unavailable')
    monkeypatch.setattr(casci_services,'prepare_casci',missing)
    panel.review.click()
    assert not panel.plan['ready'] and panel.submit.disabled
    assert 'Blocked' in panel.batch_review.value and 'saved wavefunction unavailable' in panel.batch_review.value


def test_submission_keeps_accepted_uuids_and_stops_after_an_error(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    submitted=[]
    def submit(plan):
        submitted.append(plan)
        if len(submitted)==2:raise RuntimeError('broker unavailable')
        return 'accepted-job'
    monkeypatch.setattr(casci_services,'submit_casci',submit)
    async def check():
        panel.review.click()
        panel.submit.click()
        assert panel.plan is None and panel.submit.disabled
        assert len(submitted)==2
        assert panel._batch_jobs[0]['uuid']=='accepted-job'
        assert panel._batch_jobs[1]['state']=='submission failed'
        assert all(r['state']=='not submitted' for r in panel._batch_jobs[2:])
        assert 'broker unavailable' in panel.batch_status.value
        await panel._batch_task
        assert not panel._running and panel._batch_jobs[0]['finished']
        panel.submit.click()
        assert len(submitted)==2
    asyncio.run(check())


def test_reused_sectors_launch_no_calculations(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    def reuse(uuid,electrons,norb,values,force=False):
        return {'action':'reuse','reuse_uuid':'saved','input':'saved input'}
    monkeypatch.setattr(casci_services,'prepare_casci',reuse)
    def unexpected(plan):raise AssertionError('Reused sectors must not launch workflows')
    monkeypatch.setattr(casci_services,'submit_casci',unexpected)
    panel.review.click()
    assert '0 new calculations; 6 reused' in panel.batch_review.value
    panel.submit.click()
    assert all(r['state']=='reused' and r['uuid']=='saved' for r in panel._batch_jobs)
