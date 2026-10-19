"""Independent property access and retention of interactive analysis state."""

import ipywidgets as ipw


def reference_data(*, optimized=True):
    return {'uuid': 'reference', 'optimized': optimized, 'single_point': not optimized,
        'settings': {'method': 'PBE0', 'basis': 'def2-SVP', 'charge': 0, 'multiplicity': 1,
                     'nprocs': 2, 'memory_mb': 2048, 'wallclock_seconds': 1800},
        'symbols': ['C', 'O'], 'positions': [[0, 0, 0], [0, 0, 1.2]],
        'xyz': '2\nCO\nC 0 0 0\nO 0 0 1.2\n', 'source_description': 'Reference geometry',
        'structure_uuid': 'geometry', 'levels': {'available': True},
        'summary': {'energy_hartree': -100.0}}


def test_vibrations_and_dft_do_not_construct_casci(monkeypatch):
    from aiidalab_orca import viewer, casci, orbital_workspace, vibrations
    from aiidalab_orca.app import close_widget_tree
    calls = []
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))

    def unwanted(*args, **kwargs):
        raise AssertionError('CASCI must not be constructed for another analysis')

    class VibrationPanel(ipw.VBox):
        def __init__(self, uuid):
            calls.append(('vibrations', uuid))
            self.mode = 4
            self.active = True
            super().__init__()

        def set_active(self, value):
            self.active = value

    def orbitals(*args):
        calls.append(('orbitals', args[0]['uuid']))
        return ipw.Label('DFT orbitals')

    monkeypatch.setattr(casci, 'CasciStates', unwanted)
    monkeypatch.setattr(vibrations, 'VibrationalSpectroscopy', VibrationPanel)
    monkeypatch.setattr(orbital_workspace, 'OrbitalWorkspace', orbitals)
    result = viewer.show_result(reference_data())
    try:
        assert not calls  # Overview does not prepare any optional analysis.
        vibration = result.tabs.show_section('vibrations')
        assert calls == [('vibrations', 'reference')]
        vibration.mode = 5
        result.tabs.show_section('orbitals')
        assert calls[-1] == ('orbitals', 'reference') and not vibration.active
        assert result.tabs.show_section('vibrations') is vibration
        assert vibration.mode == 5 and vibration.active
        assert len(calls) == 2
    finally:
        close_widget_tree(result)


def test_unoptimized_reference_explains_vibration_prerequisite(monkeypatch):
    from aiidalab_orca import viewer, vibrations
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))
    def unwanted(*args):
        raise AssertionError('Vibrations cannot be created for an unoptimized reference')
    monkeypatch.setattr(vibrations, 'VibrationalSpectroscopy', unwanted)
    result = viewer.show_result(reference_data(optimized=False))
    try:
        panel = result.tabs.show_section('vibrations')
        assert 'geometry optimization' in panel.value
        assert result.tabs.titles == ('Overview', 'Orbitals & density', 'States & Dyson',
                                     'Vibrations', 'XPS', 'Calculation details')
    finally:
        close_widget_tree(result)


def test_casci_is_usable_without_constructing_dyson(monkeypatch):
    from aiidalab_orca import casci, dyson
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(casci.service, 'reference_runs', lambda uuid: [])
    def unwanted(*args, **kwargs):
        raise AssertionError('Opening CASCI must not construct Dyson')
    monkeypatch.setattr(dyson, 'DysonStates', unwanted)
    panel = casci.CasciStates(reference_data(), on_inspect=lambda *args: None)
    try:
        assert panel._dyson is None and panel.analysis.value == 'states'
        assert 'No common orbitals or CASCI states' in panel.empty.value
        assert not panel.calculation.toggle.value
        panel.calculation.show()
        assert panel.calculation.body.layout.display == ''
        assert panel._dyson is None
    finally:
        close_widget_tree(panel)


def test_hidden_vibration_animations_pause_and_keep_manual_pause(monkeypatch):
    from aiidalab_orca import vibration_viewer
    from aiidalab_orca.app import close_widget_tree

    class Spectrum(ipw.VBox):
        def __init__(self, record, kind):
            self.rendered = False
            self.mode = 3
            super().__init__()

        def render(self):
            if not self.rendered:
                self.play_animation = ipw.ToggleButton(value=True)
                self.children = (self.play_animation,)
                self.rendered = True

        def set_active(self, active):
            self.active = active

    monkeypatch.setattr(vibration_viewer, 'MolecularSpectrum', Spectrum)
    tabs = vibration_viewer.spectra_view({'summary': {'raman': True}})
    try:
        ir, raman = tabs.spectra
        assert ir.play_animation.value and not raman.rendered
        ir.play_animation.value = False  # A deliberate user pause is retained.
        tabs.selected_index = 1
        assert raman.play_animation.value and not ir.play_animation.value
        raman.mode = 5
        tabs.set_active(False)
        assert not raman.play_animation.value
        tabs.set_active(True)
        assert raman.play_animation.value and raman.mode == 5
        tabs.selected_index = 0
        assert not ir.play_animation.value and not raman.play_animation.value
    finally:
        close_widget_tree(tabs)


def test_replacing_results_closes_each_owned_viewer_once():
    from aiidalab_orca.app import close_widget_tree

    class Viewer(ipw.VBox):
        count = 0

        def close(self):
            self.count += 1
            super().close()

    class Property(ipw.VBox):
        def close(self):
            for child in self.children:
                close_widget_tree(child)
            super().close()

    viewer = Viewer()
    tree = ipw.VBox([Property([viewer])])
    close_widget_tree(tree)
    close_widget_tree(tree)
    assert viewer.count == 1


def test_delayed_frame_updates_cannot_restart_hidden_animation():
    from test_vibrations import record
    from aiidalab_orca.vibration_viewer import MolecularSpectrum
    from aiidalab_orca.app import close_widget_tree
    spectrum = MolecularSpectrum(record(), 'IR')
    try:
        spectrum.render()
        spectrum.set_active(False)
        spectrum.play_animation.value = False
        # A frame emitted before the pause can arrive after its parent hid it.
        spectrum.weas._widget.animationState = {'isPlaying': True, 'currentFrame': 7, 'frameDuration': 100}
        assert not spectrum.weas._widget.animationState['isPlaying']
        assert not spectrum.play_animation.value
    finally:
        close_widget_tree(spectrum)
