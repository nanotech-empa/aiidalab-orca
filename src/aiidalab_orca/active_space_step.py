"""Inspect a prepared reference and explicitly confirm a CAS active space."""

import html

import ipywidgets as ipw

from aiida_empa_orca.casci import active_space
from . import casci_services
from .inspection import OrbitalInspection


class ActiveSpaceStep(ipw.VBox):
    def __init__(self, common_uuid, electrons, norb, confirmed, reference_prepared=None, selection_invalidated=None):
        self.common_uuid = str(common_uuid)
        self.confirmed = confirmed
        self._requires_reordering = False
        self.selection_invalidated = selection_invalidated
        self.reference = casci_services.reference_data(self.common_uuid)
        self.electrons = ipw.BoundedIntText(value=electrons, min=0, max=100,
            description='Active electrons', style={'description_width': 'initial'})
        self.norb = ipw.BoundedIntText(value=norb, min=1, max=50,
            description='Active orbitals', style={'description_width': 'initial'})
        self.summary = ipw.HTML()
        self.confirm = ipw.Button(description='Confirm this active space', icon='check',
            button_style='primary', layout=ipw.Layout(width='auto'))
        self.confirm.on_click(self._confirm)
        try:
            initial_indices = self._space()['orbitals']
        except ValueError:
            initial_indices = []
        self.inspection = OrbitalInspection(self.common_uuid, active_indices=initial_indices,
                                            apply_window=self._use_selected, allow_reordering=bool(reference_prepared))
        self.reordering = None
        self.reordering_box = ipw.VBox()
        if reference_prepared:
            from .reordering import OrbitalReordering
            self.reordering = OrbitalReordering(self.common_uuid, self._selected_space,
                                                self.inspection.export_code, reference_prepared)
            self.reordering_box.children = (self.reordering,)
            self.reordering_box.layout.display = 'none'
            self.inspection.orbitals.observe(self.reordering.invalidate, names='value')
            self.inspection.selection_input.observe(self.reordering.invalidate, names='valid')
            self.electrons.observe(self.reordering.invalidate, names='value')
        kind = self.reference['kind']
        basis = {'QRO': 'QRO spatial orbitals', 'restricted': 'restricted SCF spatial orbitals',
                 'fixed': 'imported fixed spatial orbitals'}.get(kind, kind)
        heading = ('<h3>Inspect orbitals and choose the active space</h3>'
            '<p><b>CAS input:</b> '+html.escape(basis)+'. Inspect occupations and orbital shapes, '
            'then select the source orbitals and use the selection button. '
            'Alternatively, enter an active electron/orbital count below and explicitly confirm it. '
            'The small initial numbers are examples, not a choice for your molecule.</p>'
            '<p>UNO occupations, when available, diagnose the unrestricted SCF density. '
            'Viewing UNOs does not switch the CAS input from QROs to UNOs. '
            'CASSCF orbital optimization is an optional next step after confirming this space. '
            'Its optimized orbitals must be inspected and confirmed again before subsequent calculations.</p>')
        if 'orbital_mapping' in self.reference:
            mapping = self.reference['orbital_mapping']['plan']
            heading += (f'<p><b>Verified reordered reference:</b> original source MOs '
                f'{mapping["source_active_space"]["orbitals"]} → prepared CAS MOs '
                f'{mapping["native_active_space"]["orbitals"]}. Source reference '
                f'{mapping["source_reference_uuid"]}; signed coefficients preserved. '
                'This is a separate orbital identity; original CASCI states are not reused.</p>')
        super().__init__([ipw.HTML(heading), self.inspection,
            ipw.HTML('<h4>Review the active space</h4><p>A contiguous selection can be confirmed directly. '
                'A noncontiguous selection requires explicit preparation of a new shared reference below. '
                'The backend CAS window remains contiguous in that prepared ordering.</p>'),
            ipw.HBox([self.electrons,self.norb],layout=ipw.Layout(flex_flow='row wrap')),
            self.summary,self.confirm,self.reordering_box])
        self.electrons.observe(self._review, names='value')
        self.norb.observe(self._review, names='value')
        self._review()

    def _space(self):
        start = (self.reference['n_electrons']-self.electrons.value)//2
        return active_space({'electrons':self.electrons.value,
            'orbitals':list(range(start,start+self.norb.value))},self.reference)

    def _review(self, _=None):
        if self._requires_reordering:
            self.confirm.disabled = True
            self.summary.value = '<p>Noncontiguous selection: review and prepare its new shared reference before confirmation.</p>'
            return
        try:
            space = self._space()
        except ValueError as exc:
            self.confirm.disabled = True
            self.summary.value = '<p>'+html.escape(str(exc))+'</p>'
            return
        self.confirm.disabled = False
        self.summary.value = (f'<p><b>CAS({space["electrons"]},{len(space["orbitals"])})</b> · '
            f'zero-based orbital indices {space["orbitals"][0]}–{space["orbitals"][-1]}. '
            'Confirm these choices before reviewing charge/spin states. Confirmation submits no calculation.</p>')

    def _confirm(self, _=None):
        try:
            if self._requires_reordering:
                raise ValueError('Prepare and inspect the selected reordered reference before confirming')
            self.confirmed(self.common_uuid,self._space())
        except ValueError as exc:
            self.summary.value = '<p>'+html.escape(str(exc))+'</p>'

    def _use_selected(self, indices):
        indices = list(indices)
        if not indices:
            raise ValueError('Select source orbital indices before confirming the active space')
        # Preserve the existing window-based count choice for every contiguous
        # selection, including one different from the suggested initial window.
        if self.reordering and indices != list(range(indices[0], indices[-1]+1)):
            self._requires_reordering = True
            if self.selection_invalidated:
                self.selection_invalidated()
            self.norb.value = len(indices)
            self.reordering_box.layout.display = ''
            self.confirm.disabled = True
            self.summary.value = ('<p>Review the selected original indices and active electron count, '
                'then prepare a new shared orbital reference. This selection is not yet confirmed.</p>')
            return
        self._requires_reordering = False
        self.reordering_box.layout.display = 'none'
        space = active_space({'electrons':self.reference['n_electrons']-2*indices[0],
                              'orbitals':indices},self.reference)
        self.electrons.value = space['electrons']
        self.norb.value = len(space['orbitals'])
        self.confirmed(self.common_uuid,space)

    def _selected_space(self):
        if self.inspection.kind.value == 'UNO' or self.inspection._job_uuid:
            raise ValueError('Select the CAS spatial orbitals and wait for pending inspection jobs')
        return {'electrons': self.electrons.value,
                'orbitals': self.inspection.selection_input.selected_indices()}

    def set_active(self, active):
        self.inspection.set_active(active)

    def close(self):
        if getattr(self,'_disposed',False):
            return
        self._disposed = True
        if self.reordering:
            self.reordering.close()
        self.inspection.close()
        super().close()
