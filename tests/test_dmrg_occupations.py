"""Verify the actual result table renders each stored root's occupations."""
from html.parser import HTMLParser

import pytest

from aiidalab_orca import dmrg_services as service
from aiidalab_orca.dmrg import NativeDmrg
from aiidalab_orca.widget_lifecycle import close_widget_tree


class Cells(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.rows = []
        self.cell = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, text):
        if self.cell is not None:
            self.cell += text

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.rows[-1].append(self.cell)
            self.cell = None


@pytest.mark.parametrize("nroots", [1, 3])
def test_ground_and_multiroot_result_cells_show_stored_occupations(monkeypatch, nroots):
    occupations = [[2.0, 0.0, 0.0], [1.0, 1.0, 0.0], [2.0, 0.0, 0.0]][:nroots]
    energies = [-2.0, -1.2, -0.4][:nroots]
    payload = {
        "uuid": "stored-result", "state": "finished", "exit_status": 0, "paused": False,
        "source_uuid": "stored-Hamiltonian", "checkpoint_uuid": "stored-checkpoint",
        "settings": {"max_bond_dimension": 32, "ordering": "none", "threads": 1},
        "sweep_energies": [energies, energies],
        "results": {
            "energies_hartree": energies,
            "excitation_energies_ev": [0.0, 21.769108997, 43.538217994][:nroots],
            "density_checks": [{"trace": 2.0, "natural_occupations": row} for row in occupations],
            "hamiltonian_sha256": "a" * 64, "sweep_converged": True,
            "bond_dimension_convergence_established": False,
        },
    }
    monkeypatch.setattr(service, "codes", lambda: [])
    monkeypatch.setattr(service, "history", lambda *args: [])
    monkeypatch.setattr(service, "result", lambda _: payload)
    monkeypatch.setattr(service, "submit", lambda *args: pytest.fail("Displaying stored results must not submit"))
    widget = NativeDmrg()
    try:
        widget.result_uuid.value = "stored-result"
        widget._open_result()
        rows = Cells(widget.results.children[1].value).rows
        assert rows[0] == ["Root", "Energy (Ha)", "Excitation (eV)", "1-RDM trace", "Natural occupations"]
        assert len(rows) == nroots + 1
        for index, row in enumerate(rows[1:]):
            assert len(row) == 5
            assert row[:4] == [str(index), f"{energies[index]:.12f}",
                               f"{payload['results']['excitation_energies_ev'][index]:.9f}", "2.000000000"]
            assert row[4] == ["2.000000000, 0.000000000, 0.000000000",
                              "1.000000000, 1.000000000, 0.000000000",
                              "2.000000000, 0.000000000, 0.000000000"][index]
    finally:
        close_widget_tree(widget)
