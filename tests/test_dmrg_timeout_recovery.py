"""A longer scheduler allowance must not hide native scientific failures."""
import pytest
from aiida_empa_orca.dmrg_recovery import confirmed_timeout


@pytest.mark.parametrize('workflow_exit,calcjob_exit,message,expected', [
    (402,310,'slurmstepd: JOB CANCELLED DUE TO TIME LIMIT',True),
    (402,310,'slurmstepd: Detected oom_kill event',False),
    (402,310,'Native output failed saved-state validation',False),
    (404,311,'DMRG sweeps need further convergence',False),
    (0,0,'',False),
    (402,311,'slurmstepd: JOB CANCELLED DUE TO TIME LIMIT',False),
])
def test_only_confirmed_scheduler_timeout_allows_automatic_recovery(workflow_exit,calcjob_exit,message,expected):
    assert confirmed_timeout(workflow_exit,calcjob_exit,message) is expected
