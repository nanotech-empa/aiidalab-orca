"""Broadened maxima, editable prominence filters and exact map-energy selection."""
import base64
from copy import deepcopy
import json
import re

import numpy as np
import pytest

from aiida_empa_orca.dyson_data import spectral_maxima
from aiidalab_orca.spectra import SpectralViewer


def table(poles=(-2.,1.),strengths=(.8,.4)):
    return dict(initial_state=dict(multiplicity=1),transitions=[
        dict(id=str(i),energy_ev=energy,strength=strength,side='addition',final_multiplicity=2,
             final_charge=-1,final_root=i,final_ci_norm=1.) for i,(energy,strength) in enumerate(zip(poles,strengths))])


def metadata(widget):
    payload=re.search(r'data:application/json;base64,([^\"]+)',widget.download.value).group(1)
    return json.loads(base64.b64decode(payload))


def test_maximum_of_overlapping_lorentzians_is_between_their_poles():
    omega=np.linspace(-.5,.5,10001)
    total=sum(.1/((omega-pole)**2+.1**2) for pole in (-.03,.03))
    peaks=spectral_maxima(omega,total)
    assert len(peaks)==1
    assert peaks[0]['energy_ev']==pytest.approx(0.,abs=1e-12)
    assert peaks[0]['energy_ev'] not in (-.03,.03)
    assert peaks[0]['relative_height']==1.


def test_prominence_and_height_are_separate_filters_relative_to_global_maximum():
    omega=np.arange(13,dtype=float)
    intensity=np.array([0.,0.,10.,3.5,3.5,4.,3.5,0.,0.,0.,2.,0.,0.])
    # Peak 10 is prominent but low; peak 5 is high but has a shallow local dip.
    assert [p['energy_ev'] for p in spectral_maxima(omega,intensity)]==[2.,5.]
    assert [p['energy_ev'] for p in spectral_maxima(omega,intensity,height_fraction=.1)]==[2.,5.,10.]
    assert [p['energy_ev'] for p in spectral_maxima(omega,intensity,prominence_fraction=.1,height_fraction=.1)]==[2.,10.]
    assert spectral_maxima(omega,np.zeros_like(omega))==[]


@pytest.mark.parametrize('omega,intensity,settings',[
    ([0,1,1],[0,1,0],{}),([0,1,2],[0,float('nan'),0],{}),([0,1,2],[0,-1,0],{}),
    ([0,1,2],[0,1,0],dict(prominence_fraction=-.1)),
    ([0,1,2],[0,1,0],dict(height_fraction=float('nan')))])
def test_invalid_peak_detection_inputs_fail_explicitly(omega,intensity,settings):
    with pytest.raises(ValueError):spectral_maxima(omega,intensity,**settings)


def test_gui_threshold_changes_update_maxima_without_changing_transition_weights():
    value=table()
    original=deepcopy(value)
    widget=SpectralViewer(value)
    try:
        assert widget.peak_prominence.value==5. and widget.peak_height.value==30.
        assert len(widget.peak_rows)==2
        assert 'Peak −1' in widget.plot.value and 'Peak +1' in widget.plot.value
        widget.peak_prominence.value=60.
        assert len(widget.peak_rows)==1
        widget.peak_prominence.value=5.
        assert len(widget.peak_rows)==2
        widget.peak_height.value=60.
        assert len(widget.peak_rows)==1
        assert value==original
        exported=metadata(widget)['peak_detection']
        assert exported['prominence_fraction']==.05 and exported['height_fraction']==.6
        assert exported['maxima']==widget.peak_rows
        widget.auto_peaks.value=False
        assert not widget.peak_rows and widget.use_peak.disabled
        assert widget.peak_prominence.disabled and not metadata(widget)['peak_detection']['enabled']
    finally:widget.close()


def test_using_detected_maximum_preserves_precision_and_selected_transition_set():
    value=table(poles=(0.,.07),strengths=(.4,.4))
    opened=[]
    widget=SpectralViewer(value,on_peak_use=lambda:opened.append('maps'))
    try:
        assert len(widget.peak_rows)==1
        peak=widget.peak_rows[0]['energy_ev']
        assert 0.<peak<.07 and peak!=round(peak,2)
        selected=widget.selected.value
        widget.mode.value='window'
        widget.peak_choices.value=peak
        assert not widget.use_peak.disabled
        widget._use_peak()
        assert widget.blend()['energy_ev']==peak and widget.blend()['mode']=='energy'
        assert widget.selected.value==selected and opened==['maps']
        assert metadata(widget)['peak_detection']['maxima'][0]['unshifted_energy_ev']==peak
        widget.shift.value=2.
        widget._reset()
        peak_after_shift=widget.peak_rows[0]
        assert peak_after_shift['unshifted_energy_ev']==pytest.approx(peak,abs=1e-12)
        widget.lower.value=widget.upper.value+1
        assert not widget.peak_rows and widget.use_peak.disabled
    finally:widget.close()
