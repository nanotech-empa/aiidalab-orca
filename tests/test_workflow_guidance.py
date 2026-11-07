from importlib.resources import files
from importlib import import_module
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from aiidalab_orca.guidance import workflow_guides


def test_packaged_agent_guide_is_the_declared_chat_resource():
    guides = {g['id']: g for g in workflow_guides()}
    assert {'orca.app', 'orca.casci-kondo', 'orca.vibrations'} <= guides.keys()
    guide = guides['orca.casci-kondo']
    assert guide['id'] == 'orca.casci-kondo'
    assert guide['text'] == files('aiidalab_orca').joinpath('knowledge/casci-kondo.md').read_text()
    assert 'Contract for agents in the AiiDAlab chat' in guide['text']
    assert 'does not expose\nCASCI, Dyson or Kondo' in guide['text']
    assert 'not permission' in guide['text']
    metadata = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    entry_point = metadata['project']['entry-points']['aiidalab_assistant.workflow_guides']['orca']
    module, function = entry_point.split(':')
    registered = getattr(import_module(module), function)()
    by_id = {item['id']: item for item in registered}
    assert len(by_id) == len(registered)
    assert by_id['orca.casci-kondo'] == guide
    assert by_id['orca.quantum-energy']['text'] == files('aiidalab_orca').joinpath('knowledge/quantum-energy.md').read_text()
    assert 'knowledge/*.md' in metadata['tool']['setuptools']['package-data']['aiidalab_orca']


@pytest.mark.parametrize('context,selection,question,required', [
    ({'app': 'orca'}, {}, 'What is next?', {'orca.app', 'orca.casci-kondo', 'orca.vibrations'}),
    ({'app': 'home'}, {'app': 'orca'}, 'Help with this result', {'orca.app', 'orca.casci-kondo', 'orca.vibrations'}),
    ({'app': 'home'}, {}, 'Prepare a geometry optimization', {'orca.app'}),
    ({'app': 'home'}, {}, 'Help me with IR and Raman', {'orca.app', 'orca.vibrations'}),
    ({'app': 'home'}, {}, 'Compute Kondo maps', {'orca.app', 'orca.casci-kondo'}),
])
def test_shared_chat_discovers_the_app_guide_before_provider_selection(monkeypatch, context, selection, question, required):
    shared = pytest.importorskip('aiidalab_ai_assistant.workflow_guides')
    entry = SimpleNamespace(name='orca', load=lambda: workflow_guides)
    monkeypatch.setattr(shared, 'entry_points', lambda **kwargs: [entry])
    text, catalog, sources = shared.workflow_context(question, context, selection)
    selected = {source.split('@')[0] for source in sources}
    assert required <= selected
    assert {'orca.app', 'orca.casci-kondo', 'orca.vibrations'} <= {g['id'] for g in catalog}
    guide = shared.read_workflow_guide('orca.app')
    assert guide['text'] == files('aiidalab_orca').joinpath('knowledge/orca.md').read_text()
    assert guide['text'] in text and 'orca.app@'+guide['sha256'] in sources
