"""Close real orbital-property viewers through the result replacement path."""

from types import SimpleNamespace

import ipywidgets as ipw
import pytest

from aiidalab_orca import orbitals
from aiidalab_orca.widget_lifecycle import close_widget_tree
from aiidalab_widgets_empa.cube import CubeViewer


@pytest.fixture
def orbital_panel(monkeypatch):
    monkeypatch.setattr(orbitals.service, 'source_tools', lambda uuid: {'plot': [], 'cubehandler': []})
    monkeypatch.setattr(orbitals.service, 'property_runs', lambda uuid: [])
    monkeypatch.setattr(orbitals.service, 'wavefunction_status', lambda uuid: {
        'state': 'repository', 'policy': {'threshold_mb': 100, 'stash_directory': '/configured/stash'},
        'inherited': True,
    })
    data = {'uuid': 'reference', 'symbols': ['H'], 'positions': [[0, 0, 0]],
            'levels': {'channels': [[{'spin': 0, 'index': 0, 'energy_ev': -5, 'occupation': 1}]],
                       'spin_polarized': False}}
    bounds = SimpleNamespace(lower=SimpleNamespace(value=-6), upper=SimpleNamespace(value=-4))
    panel = orbitals.OrbitalProperties(data, bounds)
    viewer = CubeViewer()
    panel._cube_view = viewer
    panel.cube_box.children = (viewer,)
    yield panel, viewer
    close_widget_tree(panel)


@pytest.mark.parametrize('close_parent_first', [False, True])
def test_property_and_parent_share_one_cube_disposal(orbital_panel, monkeypatch, close_parent_first):
    panel, viewer = orbital_panel
    unlink = viewer._cube_link.unlink
    unlinked = []

    def record_unlink():
        unlinked.append(True)
        unlink()

    monkeypatch.setattr(viewer._cube_link, 'unlink', record_unlink)
    parent = ipw.VBox([panel])
    if not close_parent_first:
        panel.close()
    close_widget_tree(parent)
    close_widget_tree(parent)
    panel.close()
    assert unlinked == [True]


def test_historical_helper_import_remains_available():
    from aiidalab_orca.app import close_widget_tree as historical
    assert historical is close_widget_tree
