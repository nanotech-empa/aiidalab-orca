"""Inspect a prepared reference and explicitly confirm a CAS active space."""

import html

import ipywidgets as ipw

from aiida_empa_orca.casci import active_space
from . import casci_services
from .inspection import OrbitalInspection


class ActiveSpaceStep(ipw.VBox):
    def __init__(self, common_uuid, electrons, norb, confirmed):
        self.common_uuid = str(common_uuid)
        self.confirmed = confirmed
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
                                            apply_window=self._use_selected)
        kind = self.reference['kind']
        basis = {'QRO': 'QRO spatial orbitals', 'restricted': 'restricted SCF spatial orbitals',
                 'fixed': 'imported fixed spatial orbitals'}.get(kind, kind)
        heading = ('<h3>Inspect orbitals and choose the active space</h3>'
            '<p><b>CAS input:</b> '+html.escape(basis)+'. Inspect occupations and orbital shapes, '
            'then select a contiguous orbital window and use its selection button. '
            'Alternatively, enter an active electron/orbital count below and explicitly confirm it. '
            'The small initial numbers are examples, not a choice for your molecule.</p>'
            '<p>UNO occupations, when available, diagnose the unrestricted SCF density. '
            'Viewing UNOs does not switch the CAS input from QROs to UNOs. '
            'CASSCF orbital optimization is an optional next step after confirming this space. '
            'Its optimized orbitals must be inspected and confirmed again before subsequent calculations.</p>')
        super().__init__([ipw.HTML(heading), self.inspection,
            ipw.HTML('<h4>Review the active space</h4><p>The current preparation supports one contiguous '
                'window in the prepared orbital ordering. Orbitals outside it remain inactive or virtual.</p>'),
            ipw.HBox([self.electrons,self.norb],layout=ipw.Layout(flex_flow='row wrap')),
            self.summary,self.confirm])
        self.electrons.observe(self._review, names='value')
        self.norb.observe(self._review, names='value')
        self._review()

    def _space(self):
        start = (self.reference['n_electrons']-self.electrons.value)//2
        return active_space({'electrons':self.electrons.value,
            'orbitals':list(range(start,start+self.norb.value))},self.reference)

    def _review(self, _=None):
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
            self.confirmed(self.common_uuid,self._space())
        except ValueError as exc:
            self.summary.value = '<p>'+html.escape(str(exc))+'</p>'

    def _use_selected(self, indices):
        indices = list(indices)
        space = active_space({'electrons':self.reference['n_electrons']-2*indices[0],
                              'orbitals':indices},self.reference)
        self.electrons.value = space['electrons']
        self.norb.value = len(space['orbitals'])
        self.confirmed(self.common_uuid,space)

    def set_active(self, active):
        self.inspection.set_active(active)

    def close(self):
        if getattr(self,'_disposed',False):
            return
        self._disposed = True
        self.inspection.close()
        super().close()
