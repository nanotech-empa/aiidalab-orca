"""Explicit populations of saved initial-state Dyson results, without new CASCI jobs."""
import html

import ipywidgets as ipw

from . import dyson_mixture_services as service


class DysonMixtures(ipw.VBox):
    def __init__(self,state_rows,on_open):
        self.state_rows,self.on_open = state_rows,on_open
        self.plan = None
        self.weights = {}  # UUID -> widgets; never retain ORM nodes.
        self.results = ipw.SelectMultiple(description='Saved Dyson results',
            style={'description_width':'150px'},layout=ipw.Layout(width='95%',height='160px'))
        self.results.observe(self._selected,names='value')
        self.refresh = ipw.Button(description='Refresh saved results',icon='refresh',layout=ipw.Layout(width='auto'))
        self.refresh.on_click(self._refresh)
        self.equal = ipw.Button(description='Set equal populations',layout=ipw.Layout(width='auto'))
        self.equal.on_click(self._equal)
        self.populations = ipw.VBox()
        self.review = ipw.Button(description='Review population mixture',icon='list',layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.combine = ipw.Button(description='Save and view mixture',icon='check',button_style='success',disabled=True,
                                  layout=ipw.Layout(width='auto'))
        self.combine.on_click(self._save)
        self.message = ipw.HTML()
        self.previous = ipw.Dropdown(description='Saved mixtures',style={'description_width':'150px'},layout=ipw.Layout(width='95%'))
        self.previous.observe(self._open,names='value')
        super().__init__([ipw.HTML('<p>Combine one saved Dyson result per initial state, using explicitly chosen statistical populations. '
            'For example, use 0.5 for the singlet and 0.5 for the triplet. These are populations of whole multiplets; '
            'the selected spin convention handles their spin factors separately. All selected results must share charge, geometry, '
            'fixed orbitals, active space and integral model. Each result contributes all of its computed transitions; '
            'this cannot supply final states that were never calculated. '
            '<b>Each initial state retains its actual transition energies.</b> Equal populations do not imply equal energies. '
            'No SCF, CASCI or Dyson coefficients are recomputed.</p>'),self.refresh,self.results,self.populations,
            self.equal,self.review,self.message,self.combine,self.previous])
        self._refresh()

    def _invalidate(self,_=None):
        self.plan,self.combine.disabled = None,True
        self.message.value = ''

    def _error(self,exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _refresh(self,_=None):
        self._invalidate()
        try:
            self.rows = service.candidates(self.state_rows)
            self.results.options = [(r['label'],r['uuid']) for r in self.rows]
            self.previous.options = [('Select a saved mixture',None)]+service.history(self.state_rows)
        except Exception as exc:
            self._error(exc)

    def _selected(self,_=None):
        self._invalidate()
        old = self.weights
        self.weights = {}
        for uuid in self.results.value:
            row = next(r for r in self.rows if r['uuid'] == uuid)
            control = ipw.FloatText(value=old[uuid].value if uuid in old else 0.,
                description=f"M{row['multiplicity']} root {row['root']} · population",
                style={'description_width':'210px'},layout=ipw.Layout(width='350px'))
            control.observe(self._invalidate,names='value')
            self.weights[uuid] = control
        self.populations.children = tuple(self.weights.values())
        for control in old.values():
            control.close()

    def _equal(self,_=None):
        if self.weights:
            for control in self.weights.values():
                control.value = 1./len(self.weights)

    def _review(self,_=None):
        self._invalidate()
        try:
            self.plan = service.review({uuid:w.value for uuid,w in self.weights.items()})
            self.message.value = f"<p>Combine {len(self.weights)} initial states and {self.plan['transition_count']} computed transitions. "\
                'Populations sum to one. Actual transition energies and raw Dyson amplitudes are preserved; each population is applied once.</p>'
            self.combine.disabled = False
        except Exception as exc:
            self._error(exc)

    def _save(self,_=None):
        if not self.plan or self.combine.disabled:
            return
        try:
            self.combine.disabled = True
            uuid = service.save(self.plan)
            self._invalidate()
            self.previous.options = [('Select a saved mixture',None)]+service.history(self.state_rows)
            self.previous.value = uuid
        except Exception as exc:
            self._invalidate()
            self._error(exc)

    def _open(self,change):
        if change['new']:
            self.on_open(str(change['new']))
