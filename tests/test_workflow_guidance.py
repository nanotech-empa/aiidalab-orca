from importlib.resources import files
import tomllib
from pathlib import Path

from aiidalab_orca.guidance import workflow_guides


def test_packaged_agent_guide_is_the_declared_chat_resource():
    guides = workflow_guides()
    assert len(guides) == 1
    guide = guides[0]
    assert guide['id'] == 'orca.casci-kondo'
    assert guide['text'] == files('aiidalab_orca').joinpath('knowledge/casci-kondo.md').read_text()
    assert 'Contract for agents in the AiiDAlab chat' in guide['text']
    assert 'does not expose\nCASCI, Dyson or Kondo' in guide['text']
    assert 'not permission' in guide['text']
    metadata = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert metadata['project']['entry-points']['aiidalab_assistant.workflow_guides']['orca'] == 'aiidalab_orca.guidance:workflow_guides'
    assert 'knowledge/*.md' in metadata['tool']['setuptools']['package-data']['aiidalab_orca']
