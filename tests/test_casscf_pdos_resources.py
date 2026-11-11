"""CASSCF's automatic PDOS stays within the separately reviewed budget."""
from copy import deepcopy
import pytest
from aiida import orm
from aiida.engine.utils import instantiate_process
from aiida_empa_orca.pdos_workflow import character_builder
from aiidalab_orca import casscf_services as service
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401
from test_l06_resources import completed_common  # noqa: F401
from test_casscf import SPACE


def test_reviewed_pdos_budget_reaches_workchain_and_serial_native_helper(completed_common,aiida_manager):
    uid,_,parts=completed_common
    code=orm.load_code(parts[2])
    export=orm.InstalledCode(computer=code.computer,filepath_executable='/test/orca_2json').store()
    helper=orm.InstalledCode(computer=code.computer,filepath_executable='/test/character').store()
    helper.base.extras.set('aiidalab_orca_role','orbital_character')
    values={'mode':'state_specific','states':[{'multiplicity':2,'weights':[1]}],
            'nprocs':2,'memory_mb':2048,'wallclock_seconds':600,'maxiter':75}
    plan=service.review(uid,SPACE,values,force=True,native_output_policy={'mode':'remote'})
    assert plan['pdos']['memory_gib']==2 and plan['pdos']['wallclock_seconds']==600 and plan['pdos']['ready']
    assert plan['pdos']['export_uuid']==str(export.uuid) and plan['pdos']['helper_uuid']==str(helper.uuid)
    other=service.review(uid,SPACE,values,force=True,native_output_policy={'mode':'remote'},
                         pdos_resources={'memory_gib':1,'wallclock_seconds':540})
    for key in ('signature','settings','input','readback_input'):assert plan[key]==other[key]
    b=service.builder(plan)
    assert b.character_memory_gib.value==2 and b.character_wallclock_seconds.value==600
    assert b.character_export_code.uuid==export.uuid and b.character_helper_code.uuid==helper.uuid
    parent=instantiate_process(aiida_manager.get_runner(),b);captured=[]
    parent.submit=lambda child:captured.append(child) or orm.CalcJobNode().store()
    try:
        assert parent.setup() is None
        parent.calculate();native=captured[0]
        assert native.metadata.options.max_memory_kb==2097152
        assert native.metadata.options.max_wallclock_seconds==600
        assert native.metadata.options.resources=={'num_machines':1,'num_mpiprocs_per_machine':2}
    finally:parent.close()
    ref=orm.load_node(uid).outputs.orbital_reference.get_dict()
    info={'source_uuid':uid,'remote_uuid':parts[1],'structure_uuid':ref['structure_uuid'],
          'charge':ref['charge'],'multiplicity':ref['source_multiplicity'],'sets':{'CASSCF':'aiida.qro'}}
    pdos=character_builder(info,'CASSCF',plan['pdos']['export_uuid'],plan['pdos']['helper_uuid'],
        b.character_memory_gib.value,wallclock_seconds=b.character_wallclock_seconds.value)
    assert pdos.metadata.options.max_memory_kb==2097152 and pdos.metadata.options.max_wallclock_seconds==600
    assert pdos.metadata.options.resources=={'num_machines':1,'num_mpiprocs_per_machine':1}
    altered=deepcopy(plan);altered['pdos_resources']['wallclock_seconds']=540
    with pytest.raises(ValueError,match='review it again'):service.builder(altered)


@pytest.mark.parametrize('resources',[{'memory_gib':0},{'wallclock_seconds':0},{'unexpected':1}])
def test_invalid_pdos_resources_fail_during_review(completed_common,resources):
    with pytest.raises(ValueError):
        service.review(completed_common[0],SPACE,{'states':[{'multiplicity':2,'weights':[1]}]},
                       force=True,pdos_resources=resources)
