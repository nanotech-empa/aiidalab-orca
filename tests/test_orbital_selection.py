"""Typed orbital selections, inclusive ranges and synchronized highlights."""

import ipywidgets as ipw
import pytest

from aiidalab_orca.orbital_selection import OrbitalIndexInput, parse_orbital_indices


@pytest.mark.parametrize('text,expected', [
    ('1 2 3 4', (1, 2, 3, 4)),
    ('1,2,3,4', (1, 2, 3, 4)),
    ('3..10', tuple(range(3, 11))),
    ('3 .. 10', tuple(range(3, 11))),
    ('1 3..10 14, 18..21', (1, *range(3, 11), 14, *range(18, 22))),
    ('4, 1 3..5 1', (1, 3, 4, 5)),
    ('0..0', (0,)),
    ('', ()),
    (' \t\n ', ()),
])
def test_indices_and_inclusive_ranges(text, expected):
    assert parse_orbital_indices(text, range(24)) == expected


@pytest.mark.parametrize('text', [
    '-1', '1.5', '1...4', '1..', '..4', '1,,2', '1;2',
    '10..3', '24', '0..1000000000000', '1+2', '__import__("os")',
])
def test_invalid_selections_are_rejected(text):
    with pytest.raises(ValueError):
        parse_orbital_indices(text, range(24))


def test_indices_must_exist_in_this_orbital_set():
    with pytest.raises(ValueError, match='Unavailable orbital indices: 2'):
        parse_orbital_indices('1..3', [0, 1, 3])
    with pytest.raises(ValueError, match='Read orbital information'):
        parse_orbital_indices('0', [])


def test_text_and_list_stay_synchronized_without_replacing_valid_typed_ranges():
    from aiidalab_orca.app import close_widget_tree
    selection = ipw.SelectMultiple(options=[(str(i), i) for i in range(24)], value=(4, 5))
    field = OrbitalIndexInput(selection)
    try:
        assert field.text.value == '4 5'
        field.text.value = '1 3..10 14, 18..21'
        expected = (1, *range(3, 11), 14, *range(18, 22))
        assert selection.value == expected
        assert field.selected_indices() == list(expected)
        assert field.text.value == '1 3..10 14, 18..21'
        selection.value = (0, 2, 5)
        assert field.text.value == '0 2 5'
        field.text.value = '3..'
        assert not field.valid and selection.value == (0, 2, 5)
        with pytest.raises(ValueError, match='Correct the orbital indices'):
            field.selected_indices()
        selection.value = (1, 3)
        assert field.valid and not field.error.value and field.text.value == '1 3'
        field.text.value = ''
        assert field.valid and selection.value == ()
        field.text.value = '99'
        selection.options = [('UNO 0', 0), ('UNO 1', 1)]
        assert field.valid and field.text.value == ''
        assert not field.error.value
    finally:
        close_widget_tree(field)
        selection.close()


def test_input_is_disabled_until_orbital_indices_are_available():
    from aiidalab_orca.app import close_widget_tree
    selection = ipw.SelectMultiple()
    field = OrbitalIndexInput(selection)
    try:
        assert field.text.disabled
        selection.options = [('Restricted 0', 0)]
        assert not field.text.disabled
        selection.value = (0,)
        assert field.text.value == '0'
        selection.options = []
        assert field.text.disabled and field.text.value == ''
    finally:
        close_widget_tree(field)
        selection.close()
