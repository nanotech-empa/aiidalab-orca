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
PLANE=dict(center=[0.,0.,0.],normal=[0.,0.,1.],offset=.2,width=3.,height=4.,resolution=64,vmin=-.1,vmax=.1,periodic=False)


def test_render_stages_one_cube_and_retrieves_only_image(aiida_profile,aiida_localhost,aiida_manager,tmp_path):
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    manifest=orm.Dict(dict={'retention':'stash','cubes':[{'filename':'a.cube','full':{'size_bytes':12}}]})
    for kind in ('repository','folder','stash'):
        b=CubeRenderCalculation.get_builder()
        lighting=dict(ambient=.4,direct=.6,gloss=.2)
        b.code=code;b.source_manifest=manifest;b.filename=orm.Str('a.cube');b.settings=orm.Dict(dict={**SETTINGS,'slice_plane':PLANE,'lighting':lighting})
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
                import json
                with folder.open('slice-plane.json') as handle:
                    assert json.load(handle)==PLANE
                with folder.open('lighting.json') as handle:
                    assert json.load(handle)==lighting
            assert info.retrieve_list==['render.png','render.log']
            copies=info.local_copy_list if kind=='repository' else info.remote_copy_list
            assert len(copies)==1 and copies[0][2]=='input.cube'
            assert info.codes_info[0].cmdline_params[:2]==['render','input.cube']
            assert info.codes_info[0].cmdline_params[-4:]==['--slice-plane','slice-plane.json','--lighting','lighting.json']
        finally:process.close()


@pytest.mark.parametrize('lighting',[dict(ambient=.4,direct=.6,gloss=float('nan')),dict(ambient=.4),dict(ambient=.4,direct=.6,gloss=2)])
def test_invalid_lighting_does_not_submit(lighting):
    from aiida_empa_orca.rendering import render_settings
    with pytest.raises(ValueError,match='Lighting'):
        render_settings({**SETTINGS,'lighting':lighting})


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


def test_saved_visualizations_persist_and_render_their_own_snapshots(aiida_profile,monkeypatch):
    from copy import deepcopy
    from aiida.common import LinkType
    from aiidalab_orca import render_services as service

    calculation=orm.CalcJobNode().store()
    manifest=orm.Dict(dict={'retention':'stash','cubes':[{'filename':'a.cube'},{'filename':'spin.cube'}]})
    manifest.base.links.add_incoming(calculation,link_type=LinkType.CREATE,link_label='manifest')
    manifest.store()
    attributes=manifest.base.attributes.all
    state={'version':1,'render':deepcopy(SETTINGS),'plane':PLANE,'show_plane':True}
    first=service.save_view(calculation.uuid,'a.cube','full','Front',state)
    state['render']['background']='#123456'
    second=service.save_view(calculation.uuid,'spin.cube','preview','Side',state)
    state['render']['background']='#000000'
    assert service.saved_view(str(calculation.uuid),first)['visualization']['render']['background']=='#FFFFFF'
    assert len(service.saved_views(str(calculation.uuid)))==2
    submitted=[]
    def submit(uuid,filename,quality,settings,*,view_name):
        submitted.append((filename,quality,settings,view_name))
        return str(len(submitted))
    monkeypatch.setattr(service,'submit_render',submit)
    report=service.render_saved_views(str(calculation.uuid),[first,second])
    assert len(report['submitted'])==2 and not report['errors']
    assert [(row[0],row[1],row[3]) for row in submitted]==[
        ('a.cube','full','Front'),('spin.cube','preview','Side')]
    assert submitted[1][2]['background']=='#123456'
    assert submitted[0][2]['slice_plane']==PLANE  # Old snapshots are upgraded only at submission.
    service.save_view(calculation.uuid,'a.cube','full','Updated',state,first)
    assert len(service.saved_views(calculation.uuid))==2
    assert service.saved_view(calculation.uuid,first)['name']=='Updated'
    service.remove_view(calculation.uuid,first)
    assert [row['id'] for row in service.saved_views(calculation.uuid)]==[second]
    with pytest.raises(ValueError,match='removed'):
        service.saved_view(calculation.uuid,first)
    # Saving UI state never modifies the scientific attributes or creates jobs.
    assert orm.load_node(manifest.uuid).base.attributes.all==attributes


def test_batch_render_reports_missing_source_without_substituting_preview(aiida_profile,monkeypatch):
    from aiidalab_orca import render_services as service
    records={'missing':dict(name='Missing full cube',filename='a.cube',quality='full',visualization={'render':SETTINGS}),
             'available':dict(name='Available preview',filename='b.cube',quality='preview',visualization={'render':SETTINGS})}
    monkeypatch.setattr(service,'saved_view',lambda uuid,key: records[key])
    def submit(uuid,filename,quality,settings,*,view_name):
        if quality=='full':raise ValueError('Full cubes were deleted')
        return 'submitted-uuid'
    monkeypatch.setattr(service,'submit_render',submit)
    result=service.render_saved_views('property-uuid',['missing','available'])
    assert result['submitted']==[{'name':'Available preview','uuid':'submitted-uuid'}]
    assert result['errors']==[{'name':'Missing full cube','message':'Full cubes were deleted'}]


def test_batch_panel_shows_a_failure_even_if_last_image_succeeds(monkeypatch):
    from aiidalab_orca import render_services as service
    from aiidalab_orca.rendering import RenderPanel
    monkeypatch.setattr(service,'renders',lambda uuid: [])
    def result(uuid,*,include_image=True):
        return dict(state='finished',finished=True,success=uuid=='good',
                    message='Renderer failed' if uuid=='bad' else '',image=b'png',filename='b.cube')
    monkeypatch.setattr(service,'result',result)
    panel=RenderPanel('property-uuid','a.cube')
    panel.process_uuid='good'
    panel._batch_jobs={'bad':'First view','good':'Second view'}
    panel._pending=['bad','good']
    assert panel._update()
    assert 'First view: failed: Renderer failed' in panel.status.value
    assert 'Second view: finished' in panel.status.value
    assert 'b.cube.png' in panel.download.value
    panel.close()
