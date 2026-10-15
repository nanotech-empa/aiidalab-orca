"""Render staging, retention, and storage-policy interface contracts."""
import io

import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.common.datastructures import StashMode
from aiida.engine.utils import instantiate_process

from aiida_empa_orca.rendering import CubeRenderCalculation
from aiidalab_orca import property_services
from test_reference import electronic_source  # noqa: F401

SETTINGS=dict(orientation=[20.,0,0,0,0,20.,0,0,0,0,20.,0,0,0,0,1.],
              iso=[[.03,'#2563B7'],[-.03,'#E3AE3B']],width=640,height=480,background='#FFFFFF',opacity=.65)


def test_render_stages_one_cube_and_retrieves_only_image(aiida_profile,aiida_localhost,aiida_manager,tmp_path):
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    manifest=orm.Dict(dict={'retention':'stash','cubes':[{'filename':'a.cube','full':{'size_bytes':12}}]})
    for kind in ('repository','folder','stash'):
        b=CubeRenderCalculation.get_builder()
        b.code=code;b.source_manifest=manifest;b.filename=orm.Str('a.cube');b.settings=orm.Dict(dict=SETTINGS)
        b.metadata.options.resources={'num_machines':1,'num_mpiprocs_per_machine':1}
        if kind=='repository':
            source=orm.FolderData();source.base.repository.put_object_from_filelike(io.BytesIO(b'preview'), 'previews/a.cube')
        else:
            root=tmp_path/kind;(root/'full_cubes').mkdir(parents=True);(root/'full_cubes/a.cube').write_bytes(b'x'*12)
            source=(orm.RemoteData(computer=aiida_localhost,remote_path=str(root)) if kind=='folder' else
                    orm.RemoteStashFolderData(stash_mode=StashMode.COPY,computer=aiida_localhost,target_basepath=str(root),source_list=['full_cubes']))
        b['source_'+kind]=source
        process=instantiate_process(aiida_manager.get_runner(),b)
        try:
            with SandboxFolder() as folder:
                info=process.prepare_for_submission(folder)
            assert info.retrieve_list==['render.png','render.log']
            copies=info.local_copy_list if kind=='repository' else info.remote_copy_list
            assert len(copies)==1 and copies[0][2]=='input.cube'
            assert info.codes_info[0].cmdline_params[:2]==['render','input.cube']
        finally:process.close()


def test_wavefunction_status_distinguishes_missing_from_unavailable(electronic_source,monkeypatch):  # noqa: F811 (pytest fixture)
    from aiida_empa_orca.reference import ArtifactUnavailable
    uuid,folder=electronic_source()
    result=property_services.wavefunction_status(uuid)
    assert result['state']=='remote' and not result['inherited']
    (folder/'aiida.gbw').unlink()
    assert property_services.wavefunction_status(uuid)['state']=='missing'
    def unavailable(_):raise ArtifactUnavailable('connection failed')
    monkeypatch.setattr(property_services,'resolve_electronic',unavailable)
    assert property_services.wavefunction_status(uuid)['state']=='unavailable'


def test_helper_selection_uses_configured_code_not_generic_python(aiida_profile,aiida_localhost):
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/usr/bin/python3',label='generic-python').store()
    with pytest.raises(ValueError,match='Code setup'):
        property_services.helper_code(aiida_localhost.uuid)
    helper=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/site/run-orca-tools.sh',
                              default_calc_job_plugin='empa_orca.electronic_storage').store()
    assert property_services.helper_code(aiida_localhost.uuid)==str(helper.uuid)
    assert all(item[1]!=str(code.uuid) for item in property_services.tool_codes(aiida_localhost.uuid)['python'])


def test_helper_options_keep_slurm_account_and_queue(aiida_profile):
    from types import SimpleNamespace
    from aiida_empa_orca.rendering import calcjob_options
    source=orm.CalcJobNode()
    source.set_option('queue_name','normal')
    source.set_option('account','project123')
    source.set_option('qos','normal')
    options=calcjob_options(SimpleNamespace(creator=source))
    assert options['account']=='project123' and options['queue_name']=='normal'
    assert options['resources']=={'num_machines':1,'num_mpiprocs_per_machine':1}
    assert options['withmpi'] is False
