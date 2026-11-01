"""App-owned XPS checks available to every shared AiiDAlab chat provider."""
from importlib.resources import files


def workflow_guides():
    return [{
        'id': 'orca.xps', 'title': 'ORCA XPS validation and recovery',
        'topics': ['orca', 'xps', 'photoemission', 'core', 'cobalt', 'binding', 'deltascf'],
        'source': 'aiidalab_orca/knowledge/xps.md',
        'text': files('aiidalab_orca').joinpath('knowledge/xps.md').read_text(),
    }]
