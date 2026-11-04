"""Application-owned instructions for the shared AiiDAlab chat."""

def workflow_guides():
    """Return fresh, packaged operating guidance for the shared AiiDAlab chat."""
    from importlib.resources import files

    return [{
        'id': 'orca.app',
        'title': 'ORCA app: geometry, orbitals, CASCI, Dyson, Kondo and IR/Raman',
        'topics': ['orca', 'molecule', 'geometry', 'optimization', 'scf', 'orbitals',
                   'casci', 'dyson', 'kondo', 'ir', 'raman'],
        'source': 'aiidalab_orca/knowledge/orca.md',
        'text': files('aiidalab_orca').joinpath('knowledge/orca.md').read_text(),
    }, {
        'id': 'orca.casci-kondo',
        'title': 'ORCA CASCI, Dyson and Kondo validation',
        'topics': ['orca', 'casci', 'casscf', 'dyson', 'kondo', 'qro', 'uno'],
        'source': 'aiidalab_orca/knowledge/casci-kondo.md',
        'text': files('aiidalab_orca').joinpath('knowledge/casci-kondo.md').read_text(),
    }, {
        'id': 'orca.vibrations',
        'title': 'ORCA harmonic IR/Raman geometry selection',
        'topics': ['orca', 'ir', 'raman', 'vibrations', 'frequencies', 'hessian'],
        'source': 'aiidalab_orca/knowledge/vibrations.md',
        'text': files('aiidalab_orca').joinpath('knowledge/vibrations.md').read_text(),
    }]
