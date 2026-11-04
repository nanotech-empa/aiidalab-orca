"""Recorded optimization reuse and explicit fixed-geometry acknowledgement."""

from types import SimpleNamespace

import ipywidgets as ipw
import pytest
from ase import Atoms
from aiida import orm

from test_reference import electronic_source


def test_unverified_source_still_requires_matching_scientific_inputs(electronic_source):
    from aiida_empa_orca.vibrations import optimized_source
    from aiidalab_orca import vibration_services as service
    uuid, _ = electronic_source()
    source = orm.load_node(uuid)
    args = (source.outputs.structure, source.inputs.settings.get_dict(), source.inputs.code, source.outputs.retrieved)
    with pytest.raises(ValueError, match='optimized geometry'):
        optimized_source(*args)
    assert optimized_source(*args, allow_unverified_geometry=True) is False
    changed = orm.StructureData(ase=Atoms('NO', positions=[[0, 0, 0], [0, 0, 2]]))
    with pytest.raises(ValueError, match='must match'):
        optimized_source(changed, *args[1:], allow_unverified_geometry=True)
    plan = service.prepare(uuid, allow_unverified_geometry=True)
    assert plan['allow_unverified_geometry'] and not plan['geometry_verified']
    assert plan['warnings'] and 'AnFreq' in plan['input_preview']
    assert 'EnGrad' not in plan['input_preview'] and 'Opt' not in plan['input_preview']


def test_supplied_geometry_needs_acknowledgement_and_review(monkeypatch):
    from aiidalab_orca import vibration_entry, vibrations
    from aiidalab_orca.app import close_widget_tree
    calls = []
    monkeypatch.setattr(vibration_entry.service, 'reference_context', lambda uuid: {'optimizations': []})
    class Panel(ipw.VBox):
        def __init__(self, uuid, **kwargs):
            calls.append((uuid, kwargs))
            self.plan = 'reviewed'
            super().__init__()
        def _invalidate(self): self.plan = None
        def set_active(self, active): self.active = active
    monkeypatch.setattr(vibrations, 'VibrationalSpectroscopy', Panel)
    entry = vibration_entry.VibrationEntry('scf')
    try:
        assert entry.route.value == 'optimize' and not calls
        entry.route.value = 'supplied'
        assert not calls
        entry.acknowledge.value = True
        assert calls == [('scf', {'allow_unverified_geometry': True})]
        entry.acknowledge.value = False
        assert entry._supplied_panel.plan is None and not entry._supplied_panel.active
    finally:
        close_widget_tree(entry)


def test_matching_optimization_is_the_default_without_submission(monkeypatch):
    from aiidalab_orca import vibration_entry
    from aiidalab_orca.app import close_widget_tree
    calls = []
    monkeypatch.setattr(vibration_entry.service, 'reference_context', lambda uuid: {
        'optimizations': [{'uuid': 'original', 'label': 'CH4 optimization', 'date': '2026-11-02'}]})
    entry = vibration_entry.VibrationEntry('scf', open_reference=lambda uuid: calls.append(uuid))
    try:
        assert entry.route.value == 'existing' and not calls
        entry.action.click()
        assert calls == ['original']
    finally:
        close_widget_tree(entry)


def test_ir_use_final_geometry_opens_analysis_instead_of_preparing_scf():
    from aiidalab_orca.app import OrcaApp
    calls = []
    app = SimpleNamespace(analysis_chooser=SimpleNamespace(choice=SimpleNamespace(value='vibrations')),
                          _open_vibration_reference=lambda uuid: calls.append(uuid))
    OrcaApp.use_geometry(app, 'original')
    assert calls == ['original']


def test_packaged_vibration_guide_explains_the_acknowledged_route():
    from importlib.resources import files
    from aiidalab_orca.guidance import workflow_guides
    guide = next(g for g in workflow_guides() if g['id'] == 'orca.vibrations')
    assert guide['text'] == files('aiidalab_orca').joinpath('knowledge/vibrations.md').read_text()
    assert 'No gradient check or optimization is' in guide['text']


def test_optimization_match_ignores_process_count_but_keeps_method(electronic_source):
    from aiida.common import LinkType
    from aiida.engine import ProcessState
    from aiida_empa_orca.reference import PROCESS_TYPE
    from aiidalab_orca.vibration_services import reference_context
    uuid, _ = electronic_source(optimization=True)
    original = orm.load_node(uuid)
    def scf_reference(method):
        node = orm.WorkChainNode(process_type=PROCESS_TYPE)
        settings = dict(original.inputs.settings.get_dict(), nprocs=4, method=method)
        for name, value in {'settings': orm.Dict(dict=settings).store(), 'code': original.inputs.code,
                            'structure': original.outputs.structure}.items():
            node.base.links.add_incoming(value, link_type=LinkType.INPUT_WORK, link_label=name)
        node.store()
        for name in ('structure', 'retrieved', 'output_parameters'):
            original.outputs[name].base.links.add_incoming(node, link_type=LinkType.RETURN, link_label=name)
        node.set_process_state(ProcessState.FINISHED)
        node.set_exit_status(0)
        return str(node.uuid)
    matches = reference_context(scf_reference(original.inputs.settings.get_dict()['method']))
    assert [row['uuid'] for row in matches['optimizations']] == [uuid]
    assert not reference_context(scf_reference('B3LYP'))['optimizations']
