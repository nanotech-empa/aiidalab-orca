"""Provider-neutral quantum-energy guidance without ORM or SDK imports."""

from importlib.resources import files


def workflow_guides():
    return [
        {
            "id": "orca.quantum-energy",
            "title": "ORCA CAS energy levels: ORCA, simulator or QPU",
            "topics": [
                "orca",
                "casci",
                "quantum",
                "qpu",
                "simulator",
                "hamiltonian",
                "energy levels",
                "sqdrift",
            ],
            "source": "aiidalab_orca/knowledge/quantum-energy.md",
            "text": files("aiidalab_orca")
            .joinpath("knowledge/quantum-energy.md")
            .read_text(),
        }
    ]


def combined_workflow_guides():
    """Register all ORCA guides under the app identity used by chat context."""
    from .guidance import workflow_guides as app_guides

    guides = app_guides()
    existing = {guide["id"] for guide in guides}
    return guides + [
        guide for guide in workflow_guides() if guide["id"] not in existing
    ]
