"""Text indices synchronized with an orbital selection list."""

import html
import re

import ipywidgets as ipw
from traitlets import Bool


_TERM = r'[0-9]+(?:\s*\.\.\s*[0-9]+)?'
_SELECTION = re.compile(rf'\s*{_TERM}(?:(?:\s*,\s*|\s+){_TERM})*\s*')


def parse_orbital_indices(text, available):
    """Read zero-based indices and inclusive ranges without evaluating code."""
    if not text.strip():
        return ()
    if not _SELECTION.fullmatch(text):
        raise ValueError('Use non-negative orbital indices, separated by spaces or commas, '
                         'and inclusive ranges such as 3..10.')
    available = set(available)
    if not available:
        raise ValueError('Read orbital information before selecting indices.')
    selected = set()
    for term in re.findall(_TERM, text):
        bounds = re.split(r'\s*\.\.\s*', term)
        start, end = int(bounds[0]), int(bounds[-1])
        if end < start:
            raise ValueError(f'Range {start}..{end} runs backwards; use increasing indices.')
        if start < min(available) or end > max(available):
            raise ValueError(f'Choose indices available in this orbital set '
                             f'({min(available)}–{max(available)}).')
        selected.update(range(start, end + 1))
    missing = selected - available
    if missing:
        raise ValueError('Unavailable orbital indices: '+', '.join(map(str, sorted(missing))))
    return tuple(sorted(selected))


class OrbitalIndexInput(ipw.VBox):
    """Keep typed indices and highlighted rows in agreement in both directions."""

    valid = Bool(True)

    def __init__(self, selection, *, style=None):
        self.selection = selection
        self._updating = False
        self.text = ipw.Text(description='Orbital indices', style=style or {},
                            placeholder='e.g. 1 3..10 14, 18..21',
                            continuous_update=True, layout=ipw.Layout(width='95%'))
        self.error = ipw.HTML()
        super().__init__([self.text, ipw.HTML(
            '<p>Zero-based indices, matching the list below. Use spaces or commas and inclusive '
            'ranges: <code>3..10</code> includes 3 and 10; '
            '<code>1 3..10 14</code> mixes indices and ranges. '
            'Typing updates the highlights; clicking the list updates this field. '
            'Selecting orbitals alone does not change the CAS or submit a calculation.</p>'), self.error])
        self.text.observe(self._from_text, names='value')
        self.selection.observe(self._from_list, names=['value', 'options'])
        self._from_list()

    def _from_text(self, _=None):
        if self._updating:
            return
        try:
            indices = parse_orbital_indices(self.text.value,
                                           dict(self.selection.options).values())
        except ValueError as exc:
            self.valid = False
            self.error.value = ('<p style="color:#a02020">'+html.escape(str(exc))+
                                ' Highlights are unchanged. Correct the field or select rows in the list.</p>')
            return
        self._updating = True
        try:
            self.selection.value = indices
        finally:
            self._updating = False
        self.error.value = ''
        self.valid = True

    def _from_list(self, _=None):
        if self._updating:
            return
        self._updating = True
        try:
            self.text.disabled = not bool(self.selection.options)
            self.text.value = ' '.join(map(str, self.selection.value))
            self.error.value = ''
            self.valid = True
        finally:
            self._updating = False

    def selected_indices(self):
        if not self.valid:
            raise ValueError('Correct the orbital indices before reviewing or applying this selection.')
        return sorted(self.selection.value)

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        self.selection.unobserve(self._from_list, names=['value', 'options'])
        self.text.unobserve(self._from_text, names='value')
        super().close()
