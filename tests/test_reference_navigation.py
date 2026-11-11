"""Reference changes detach old views and cannot confirm stale orbital data."""

from copy import deepcopy

import ipywidgets as ipw
import pytest

from aiidalab_orca import casci, casscf, inspection, inspection_services, viewer
from aiidalab_orca.presentation import LazyStack, LazyTabs
from aiidalab_orca.widget_lifecycle import close_widget_tree
from test_result_navigation import reference_data


@pytest.fixture
def reference_switch(monkeypatch):
    refs = {
        'optimized': {'kind': 'CASSCF', 'occupations': [1.9, 1., .1]},
        'original': {'kind': 'QRO', 'occupations': [2., 1., 0.]},
    }
    monkeypatch.setattr(viewer, 'molecule', lambda *a: ipw.Label('Geometry'))
    monkeypatch.setattr(casci.service, 'reference_runs', lambda _: [
        {'uuid': uid, 'kind': ref['kind'], 'reference_uuid': uid+'-orbitals'}
        for uid, ref in refs.items()])
    monkeypatch.setattr(casci.service, 'reference_data', lambda uid: {
        'kind': refs[uid]['kind'], 'n_electrons': 23, 'n_orbitals': 67,
        'charge': 0, 'source_multiplicity': 2})
    monkeypatch.setattr(casci.service, 'runs', lambda _: [])
    monkeypatch.setattr(casci.service, 'results', lambda *a: [])
    monkeypatch.setattr(casci.service, 'execution_details', lambda _: {
        'computer': 'localhost', 'code': 'orca', 'nprocs': 2,
        'memory_mb': 2048, 'wallclock_seconds': 600})

    def catalog(uid):
        ref = refs[uid]
        return {'uuid': uid+'-catalog', 'data': {
            'orbital_reference_uuid': uid+'-orbitals', 'n_electrons': 23,
            'n_orbitals': 67, 'sets': {ref['kind']: {'levels': [
                {'index': i, 'occupation': occupation}
                for i, occupation in zip([10, 11, 12], ref['occupations'])]}}}}

    monkeypatch.setattr(inspection_services, 'catalog', catalog)
    monkeypatch.setattr(inspection_services, 'codes', lambda _: {
        'export': [], 'plot': [], 'cubehandler': []})
    monkeypatch.setattr(inspection_services, 'cube_runs', lambda uid, kind: [
        (kind+' previews', uid+'-cubes')])
    monkeypatch.setattr(inspection.property_services, 'property_result', lambda uid: {
        'finished': True, 'successful': True, 'full_cube_path': '/external/'+uid,
        'manifest': {'retention': 'leave', 'cubes': [
            {'filename': uid+'-0012.cube'}]}})
    monkeypatch.setattr(inspection.OrbitalInspection, '_show_cube', lambda self, *a:
        setattr(self.cube_box, 'children', (ipw.Label(self.cube.value),)))

    class CasscfPanel(ipw.VBox):
        def __init__(self, uid, space, callback):
            self.reference_uuid, self.space = uid, deepcopy(space)
            self.plan = None
            super().__init__([ipw.Label(uid)])

    monkeypatch.setattr(casscf, 'CasscfOrbitals', CasscfPanel)

    def forbidden(*a, **k):
        raise AssertionError('Reference navigation must not submit calculations')

    monkeypatch.setattr(casci.service, 'prepare_common', forbidden)
    monkeypatch.setattr(casci.service, 'submit_common', forbidden)
    monkeypatch.setattr(casci.service, 'submit_casci', forbidden)
    monkeypatch.setattr(inspection_services, 'submit_catalog_plan', forbidden)
    monkeypatch.setattr(inspection_services, 'submit_cubes', forbidden)
    data = reference_data() | {'active_space': {'electrons': 3, 'orbitals': [10, 11, 12]}}
    result = viewer.ResultsView(data)
    panel = result.open_analysis('prepare')
    panel.electrons.value, panel.norb.value = 3, 3
    yield result, panel, refs
    close_widget_tree(result)


def test_switch_remounts_catalog_cubes_confirmation_and_casscf(reference_switch):
    result, panel, refs = reference_switch
    old_active = old_casscf = None
    for uid in ('optimized', 'original', 'optimized'):
        result.open_analysis('prepare')
        panel.reference.value = uid
        if old_active is not None:
            assert result.confirmed_space is None
            assert 'active' not in result.tabs.panels
            assert 'casscf' not in result.tabs.panels
            assert old_active not in result.tabs.children
            assert old_casscf not in result.tabs.children
            assert old_active.comm is None and old_casscf.comm is None
        active = result.open_analysis('active')
        assert active is result.tabs.children[result.tabs.section_keys.index('active')]
        assert active.common_uuid == active.inspection.common_uuid == uid
        assert active.reference['kind'] == active.inspection.kind.value == refs[uid]['kind']
        assert active.inspection.catalog_record['uuid'] == uid+'-catalog'
        assert active.inspection.catalog_record['data']['orbital_reference_uuid'] == uid+'-orbitals'
        levels = active.inspection.catalog_record['data']['sets'][refs[uid]['kind']]['levels']
        assert [r['occupation'] for r in levels] == refs[uid]['occupations']
        assert active.inspection.previous.value == uid+'-cubes'
        assert active.inspection.cube.value == uid+'-cubes-0012.cube'
        assert active.inspection.cube_box.children[0].value == uid+'-cubes-0012.cube'
        active.confirm.click()
        assert result.navigation.value == 'energy'
        assert result.confirmed_space == (uid, 3, 3)
        current_casscf = result.open_analysis('casscf')
        assert current_casscf.reference_uuid == uid
        assert current_casscf.space == {'electrons': 3, 'orbitals': [10, 11, 12]}
        assert current_casscf is not old_casscf
        current_casscf.plan = {'reference_uuid': uid}
        old_active, old_casscf = active, current_casscf


def test_stale_confirmation_rejected_even_after_return_to_same_reference(reference_switch):
    result, panel, _ = reference_switch
    panel.reference.value = 'optimized'
    old = result.open_analysis('active')
    old.confirm.click()
    result.open_analysis('prepare')
    panel.reference.value = 'original'
    panel.reference.value = 'optimized'
    current = result.open_analysis('active')
    old.confirm.click()  # A queued event from a disposed view must not be accepted.
    assert result.navigation.value == 'active'
    assert result.confirmed_space is None
    assert 'reference changed' in old.summary.value
    with pytest.raises(ValueError, match='reference changed'):
        old.inspection.apply_window([10, 11, 12])
    current.confirm.click()
    assert result.navigation.value == 'energy'
    assert result.confirmed_space == ('optimized', 3, 3)


@pytest.mark.parametrize('container', [LazyStack, LazyTabs])
def test_lazy_invalidation_detaches_before_closing_and_remounts_once(container):
    created, closed = [], []
    tabs = None

    class Panel(ipw.VBox):
        def __init__(self):
            super().__init__([ipw.Label('Owned child')])
            created.append(self)

        def close(self):
            if self.comm is not None:
                assert self not in tabs.children
                closed.append(self)
            super().close()

    tabs = container([('placeholder', 'First', lambda: ipw.Label('First')),
                      ('active', 'Active', Panel)])
    first = tabs.show_section('active')
    tabs.invalidate_section('active')
    assert first not in tabs.children and first.comm is None
    assert first.children[0].comm is None and closed == [first]
    second = tabs.show_section('active')  # selected_index did not change.
    assert created == [first, second]
    assert second is tabs.panels['active'] is tabs.children[1]
    assert tabs.show_section('active') is second
    tabs.invalidate_section('active')
    tabs.invalidate_section('active')
    assert closed == [first, second]
    close_widget_tree(tabs)
