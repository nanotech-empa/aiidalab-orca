"""UI units and explicit spin choices preserve the scientific request."""

import ipywidgets as ipw
import pytest
from ase import Atoms
from traitlets import TraitError

from aiidalab_orca.configuration import GeometrySettings
from aiidalab_orca.resources import MemoryInput, memory_label


def test_memory_display_roundtrip_preserves_existing_mib_and_observers():
    widget = MemoryInput(value=2048)
    changes = []
    widget.observe(lambda event: changes.append(event["new"]), names="value")
    try:
        assert widget.gib.value == 2
        widget.gib.value = 4
        assert widget.value == 4096 and changes == [4096]
        widget.value = 1234
        assert widget.gib.value == 1234 / 1024
        widget.gib.value = 1.1
        assert widget.value == round(1.1 * 1024)
        assert memory_label(2048) == "2 GiB"
        widget.gib.value = 0
        assert widget.value == 256
        widget.value = 2 ** 30
        assert widget.value == 1048576 and widget.gib.value == 1024
        for value in (float("nan"), float("inf")):
            with pytest.raises(TraitError):
                widget.gib.value = value
        assert widget.value == 1048576
    finally:
        widget.close()


def test_multiplicity_is_editable_with_finite_allowed_values_and_no_checkbox():
    widget = GeometrySettings()
    try:
        widget.set_molecule(Atoms("H2"))
        assert widget.multiplicity.value == 1 and not widget.multiplicity.disabled
        assert "allowed multiplicities: 1, 3." in widget.spin_hint.value
        assert not isinstance(widget.auto_multiplicity, ipw.Widget)
        widget.multiplicity.value = 3
        widget.charge.value = 1
        assert widget.multiplicity.value == 3
        assert "allowed multiplicities: 2." in widget.spin_hint.value
        assert "not allowed" in widget.spin_hint.value
        widget.multiplicity.value = 2
        assert "not allowed" not in widget.spin_hint.value
        widget.set_molecule(Atoms("N"))
        widget.charge.value = 0
        assert widget.multiplicity.value == 2
        assert "allowed multiplicities: 2, 4, 6, 8." in widget.spin_hint.value
    finally:
        widget.close()
