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
    monkeypatch.setattr(casci_services,'active_casci_batch',lambda _:None)
    monkeypatch.setattr(casci_services,'execution_details',lambda _:{'code':'orca','computer':'test-computer',
        'nprocs':2,'memory_mb':2048,'wallclock_seconds':1800})
    monkeypatch.setattr(casci_services,'runs',lambda _:[])
    monkeypatch.setattr(casci_services,'results',lambda *_:[])
    monkeypatch.setattr(casci_services,'progress',lambda uuid:{'state':'finished','finished':True,
        'success':True,'message':'','reports':[]})
    prepared=[]
    def prepare(uuid,electrons,norb,values,force=False,*,native_output_policy=None):
        space=backend.active_space({'electrons':electrons,'orbitals':[4,5]},ref)
        settings=backend.casci_settings(values,ref,space)
        plan={'reference_uuid':uuid,'active_space':space,'settings':settings,'force_recompute':force,
              'action':'compute','reuse_uuid':None,'input':backend.casci_input(ref,space,settings),
              'native_output_policy':native_output_policy}
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
    monkeypatch.setattr(casci_services,'submit_casci_batch',lambda plan:submitted.append(plan))
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


def test_one_persistent_batch_and_duplicate_submit_is_blocked(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    submitted=[]
    monkeypatch.setattr(casci_services,'submit_casci_batch',lambda plan:submitted.append(plan) or 'batch-id')
    queued={'charge':0,'multiplicity':1,'uuid':None,'state':'queued','finished':False,'success':False,'message':''}
    replies=iter([dict(finished=False,sectors=[queued]),
                  dict(finished=True,sectors=[dict(queued,uuid='sector-id',state='finished',finished=True,success=True)])])
    monkeypatch.setattr(casci_services,'casci_batch_progress',lambda _:next(replies))
    async def check():
        panel.review.click()
        assert 'Sectors run sequentially' in panel.batch_review.value
        assert 'may run concurrently' not in panel.batch_review.value
        panel.submit.click();panel.submit.click();panel._submit_casci()
        assert len(submitted)==1 and panel._batch_uuid=='batch-id'
        assert panel.plan is None and panel.submit.disabled
        await panel._batch_task
        assert not panel._running and panel._batch_jobs[0]['finished']
        panel.submit.click();assert len(submitted)==1
    asyncio.run(check())


def test_failed_batch_submission_requires_new_review(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    attempts=[]
    def fail(plan):attempts.append(plan);raise RuntimeError('broker unavailable')
    monkeypatch.setattr(casci_services,'submit_casci_batch',fail)
    panel.review.click();panel.submit.click();panel.submit.click()
    assert len(attempts)==1 and panel.plan is None and panel.submit.disabled
    assert not panel._running and 'broker unavailable' in panel.message.value


def test_review_reconnects_to_active_batch_without_submission(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    monkeypatch.setattr(casci_services,'active_casci_batch',lambda _:'existing-batch')
    monkeypatch.setattr(casci_services,'casci_batch_progress',lambda _:dict(finished=False,sectors=[]))
    monkeypatch.setattr(casci_services,'submit_casci_batch',lambda _:pytest.fail('Do not duplicate an active batch'))
    panel.review.click()
    assert panel._batch_uuid=='existing-batch' and panel._running and panel.submit.disabled
    assert 'existing-batch' in panel.batch_status.value


def test_reused_sectors_launch_no_calculations(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    def reuse(uuid,electrons,norb,values,force=False,**kwargs):
        return {'action':'reuse','reuse_uuid':'saved','input':'saved input'}
    monkeypatch.setattr(casci_services,'prepare_casci',reuse)
    def unexpected(plan):raise AssertionError('Reused sectors must not launch workflows')
    monkeypatch.setattr(casci_services,'submit_casci',unexpected)
    panel.review.click()
    assert '0 new calculations; 6 reused' in panel.batch_review.value


def test_retention_is_reviewed_and_editing_it_invalidates_submission(batch_panel):
    panel, prepared, _ = batch_panel
    panel.full_files.mode.value = 'stash'
    panel.full_files.directory.value = '/user/chosen/stash'
    panel.review.click()
    assert prepared and all(p['native_output_policy'] == {
        'mode': 'stash', 'stash_directory': '/user/chosen/stash', 'maxsizeoutput': 5 * 1024**2} for p in prepared)
    assert '/user/chosen/stash' in panel.batch_review.value
    assert 'Native text output up to 5 MiB is retrieved unchanged' in panel.batch_review.value
    assert not panel.submit.disabled
    panel.full_files.mode.value = 'remote'
    assert panel.submit.disabled and panel.plan is None
    panel.submit.click()
    assert panel._batch_jobs == []


def test_status_outage_after_submission_keeps_batch_locked(batch_panel,monkeypatch):
    panel,_,_=batch_panel
    monkeypatch.setattr(casci_services,'submit_casci_batch',lambda _:'accepted-batch')
    def unavailable(_):raise OSError('temporary status outage')
    monkeypatch.setattr(casci_services,'casci_batch_progress',unavailable)
    async def end_poll(_):raise asyncio.CancelledError
    monkeypatch.setattr(asyncio,'sleep',end_poll)
    async def check():
        panel.review.click();panel.submit.click()
        await panel._batch_task
        assert panel._batch_uuid=='accepted-batch' and panel._running
        assert panel.plan is None and panel.submit.disabled
        assert 'temporary status outage' in panel.message.value
    asyncio.run(check())
