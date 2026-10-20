"""Fixed-grid compatibility, legacy provenance and reviewed app recovery."""
import io
import json
from pathlib import Path

import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.engine import ProcessState
from ase import Atoms

from aiida_empa_orca import cobalt_xps as co

FILES=Path(__file__).parent/'fixtures'/'xps_spin'


def test_native_generated_grids_are_required_not_just_echoed_input():
    text=(FILES/'copc-fixed-cosx-grids.out').read_text()
    parsed=co.integration_metadata(text,co.model_settings())
    assert [g['points'] for g in parsed['generated_cosx_grids']]==[183635]*3
    assert parsed['integration_protocol']==co.integration_protocol()
    for changed in (text.replace('183635','86516',1),
                    text.replace('AngularGrid ... 3','AngularGrid ... 2',1),
                    text[:text.index('GRIDX 3')],
                    '! AngularGridX 3,3,3\n'):
        with pytest.raises(ValueError,match='COSX grid'):
            co.integration_metadata(changed,co.model_settings())


def test_legacy_protocol_is_distinct_and_cannot_seed_new_spectrum(aiida_profile):
    legacy=co.model_settings({'protocol':co.LEGACY_PROTOCOL})
    assert legacy['cosx_grid'] is None
    assert co.model_identity(legacy)!=co.model_identity(co.model_settings())
    assert not co.reference_compatible({'protocol':co.LEGACY_PROTOCOL})
    with pytest.raises(ValueError,match='Update required'):
        co.require_consistent_reference({'protocol':co.LEGACY_PROTOCOL})
    with pytest.raises(ValueError,match='read-only'):
        co.input_text(orm.StructureData(ase=Atoms('C32H16CoN8')),'avas',legacy)
    # Revalidate actual legacy output without inventing new numerical metadata.
    node=orm.CalcJobNode(process_type=co.CALC_PROCESS)
    for key,value in {'stage':orm.Str('avas').store(),'model':orm.Dict(dict=legacy).store()}.items():
        node.base.links.add_incoming(value,link_type=LinkType.INPUT_CALC,link_label=key)
    node.store()
    text=(FILES/'copc-avas-excerpt.out').read_text()
    expected=co.parse_reference(text,'avas')
    retrieved=orm.FolderData();retrieved.base.repository.put_object_from_filelike(io.StringIO(text),'aiida.out')
    for key,value in {'reference':orm.Dict(dict=expected),'retrieved':retrieved}.items():
        value.base.links.add_incoming(node,link_type=LinkType.CREATE,link_label=key);value.store()
    node.set_process_state(ProcessState.FINISHED);node.set_exit_status(0)
    assert co.validated_calculation(node)==expected
    assert 'integration_protocol' not in expected


def test_reconvergence_keeps_active_space_and_does_not_repeat_avas_rotation(aiida_profile):
    structure=orm.StructureData(ase=Atoms('C32H16CoN8'))
    parent={'stage':'valence','valence_selection':{'swaps':[[140,141]]}}
    text=co.input_text(structure,'valence',co.model_settings(),parent)
    assert 'rotate' not in text
    assert 'nroots 70,20' in text and 'maxiter 100' in text and 'GTol 1e6' not in text
    assert '* xyzfile 0 2' in text and 'Opt' not in text
    assert text.index('TightSCF')<text.index('AngularGridX 3,3,3')<text.index('* xyzfile')


def test_native_fixed_grid_restart_and_natural_rotation_pass_unchanged_guard():
    text=(FILES/'copc-fixed-natural-excerpt.out').read_text()
    parent=json.loads((FILES/'copc-fixed-neutral-reference.json').read_text())
    parsed=co.parse_reference(text,'spectator',parent,co.model_settings())
    assert abs(parsed['ground_energy_hartree']-parent['ground_energy_hartree'])<1e-7
    assert abs(parsed['canonicalization_energy_change_hartree'])<1e-7
    assert parsed['generated_cosx_grids']==parent['generated_cosx_grids']
    assert parsed['orbital_optimization_performed'] is False
    with pytest.raises(ValueError,match='Frozen neutral energy differs'):
        co.parse_reference(text,'spectator',parent|{'ground_energy_hartree':parent['ground_energy_hartree']+1e-5},co.model_settings())
    altered=dict(parent);altered['generated_cosx_grids']=[g|{'points':g['points']+1} for g in parent['generated_cosx_grids']]
    with pytest.raises(ValueError,match='Generated COSX grids differ'):
        co.parse_reference(text,'spectator',altered,co.model_settings())


def test_direct_workflow_rejects_legacy_reference_before_any_calcjob(aiida_profile,aiida_localhost,monkeypatch,tmp_path):
    from aiida.engine import run_get_node
    from aiida_empa_orca.cobalt_workchains import CobaltXpsWorkChain,valence_restart_source
    structure=orm.StructureData(ase=Atoms('C32H16CoN8')).store()
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    parent=orm.CalcJobNode(process_type=co.CALC_PROCESS)
    for key,value in {'structure':structure,'code':code,'stage':orm.Str('valence').store(),
                      'model':orm.Dict(dict={'protocol':co.LEGACY_PROTOCOL}).store()}.items():
        parent.base.links.add_incoming(value,link_type=LinkType.INPUT_CALC,link_label=key)
    parent.store()
    for key,value in {'reference':orm.Dict(dict={'protocol':co.LEGACY_PROTOCOL,'stage':'valence'}),
                      'retrieved':orm.FolderData(),
                      'remote_folder':orm.RemoteData(computer=aiida_localhost,remote_path=str(tmp_path/'deleted-scratch'))}.items():
        value.base.links.add_incoming(parent,link_type=LinkType.CREATE,link_label=key);value.store()
    parent.set_process_state(ProcessState.FINISHED);parent.set_exit_status(0)
    # This test isolates orchestration from the native parser covered above.
    monkeypatch.setattr(co,'validated_calculation',lambda node: node.outputs.reference.get_dict())
    _,node=run_get_node(CobaltXpsWorkChain,structure=structure,code=code,helper_code=code,
        storage_policy=orm.Dict(dict={'threshold_mb':100,'stash_directory':str(tmp_path/'stash')}),
        valence_reference=parent.outputs.reference,valence_retrieved=parent.outputs.retrieved,
        valence_folder=parent.outputs.remote_folder,model=orm.Dict(dict=co.model_settings()))
    assert node.exit_status==400 and not node.called_descendants
    assert any('Update required' in entry.message for entry in orm.Log.collection.get_logs_for(node))
    other=orm.StructureData(ase=Atoms('C32H16CoN8')).store()
    with pytest.raises(ValueError,match='producing calculation'):
        valence_restart_source(other,code,parent.outputs.reference,parent.outputs.retrieved,
                               parent.outputs.remote_folder,co.model_settings())


def test_widget_blocks_legacy_and_requires_review_for_recovery(monkeypatch):
    from aiidalab_orca import cobalt_services as service
    from aiidalab_orca.cobalt_view import CobaltXpsPanel
    from aiidalab_orca.app import close_widget_tree
    rows=[{'uuid':'old','date':'2026-10-20','state':'finished','success':True,'compatible':False}]
    monkeypatch.setattr(service,'reference_info',lambda _: {})
    monkeypatch.setattr(service,'valence_runs',lambda _: rows)
    monkeypatch.setattr(service,'spectrum_runs',lambda _: [])
    monkeypatch.setattr(service,'reference_status',lambda _,uid: {
        'compatible':uid=='new','recoverable':uid=='old',
        'message':'Update required' if uid=='old' else 'Ready'})
    calls=[]
    def recovery(*args,**kwargs):
        calls.append(args)
        return {'description':'Reuse geometry and orbitals; reconverge neutral only.','orbital_location':'repository'}
    monkeypatch.setattr(service,'prepare_recovery',recovery)
    widget=CobaltXpsPanel('source')
    try:
        assert widget.references.value=='old'
        assert widget.review_spectrum.disabled and widget.submit.disabled and widget.reconverge.disabled
        assert 'Update required' in widget.reference_notice.value
        assert 'update required' in widget.references.options[1][0]
        assert 'Consistent grid (recommended)' in widget.integration.value
        widget.review_recovery.click()
        assert calls==[('source','old')] and not widget.reconverge.disabled
        assert widget.prepare.disabled and widget.submit.disabled
        widget.force.value=True
        assert widget.reconverge.disabled and widget.plan is None
        rows.insert(0,{'uuid':'new','date':'2026-10-20','state':'finished','success':True,'compatible':True})
        widget._refresh(preferred_reference='new')
        assert widget.references.value=='new' and not widget.review_spectrum.disabled
        assert widget.submit.disabled and widget.recovery_controls.layout.display=='none'
    finally:close_widget_tree(widget)


def test_widget_missing_wavefunction_leaves_recovery_disabled(monkeypatch):
    from aiidalab_orca import cobalt_services as service
    from aiidalab_orca.cobalt_view import CobaltXpsPanel
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(service,'reference_info',lambda _: {})
    monkeypatch.setattr(service,'valence_runs',lambda _: [
        {'uuid':'old','date':'2026-10-20','state':'finished','success':True,'compatible':False}])
    monkeypatch.setattr(service,'spectrum_runs',lambda _: [])
    monkeypatch.setattr(service,'reference_status',lambda *args: {'compatible':False,'recoverable':True,'message':'Update required'})
    def missing(*args,**kwargs):raise ValueError('Saved valence orbitals are unavailable; rebuild orbital preparation.')
    monkeypatch.setattr(service,'prepare_recovery',missing)
    widget=CobaltXpsPanel('source')
    try:
        widget.review_recovery.click()
        assert 'unavailable' in widget.message.value and widget.reconverge.disabled and widget.submit.disabled
    finally:close_widget_tree(widget)
