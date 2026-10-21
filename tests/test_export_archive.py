"""Wavefunction archives preserve exact JSON values while writing incrementally."""
import gzip
import json

import pytest

from aiida_empa_orca.scripts.export_dyson import write_export


def test_archive_matches_previous_decompressed_bytes_and_is_deterministic(tmp_path):
    payload = {'schema_version':1,'state_uuid':'original-state',
        'wavefunction':{'Molecule':{'Atoms':[{'Element':'Zn','Coords':[1.25,-0.0,1e-250]}],
            'description':'μ scan; original orbitals',
            'MolecularOrbitals':{'MOs':[{'MOCoefficients':[.12345678901234567,-.0312345678901234,1e-12]}]},
            'S-Matrix':[[1.,-2.3e-17],[-2.3e-17,1.]]}},
        'ci_roots':{'0':{'coefficients':{'[20u]':-.9999999999,'[02u]':1e-9},
                         'norm':.9999999815364}}}
    expected = json.dumps(payload,allow_nan=False,separators=(',',':')).encode()
    path = tmp_path/'state.json.gz'
    write_export(path,payload)
    first = path.read_bytes()
    assert gzip.decompress(first) == expected
    assert json.loads(gzip.decompress(first)) == payload
    assert first[4:8] == b'\x00'*4  # No wall-clock timestamp enters the archive.
    write_export(path,payload)
    assert path.read_bytes() == first


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf')])
def test_nonfinite_coefficients_are_rejected(tmp_path,value):
    with pytest.raises(ValueError,match='Out of range float values'):
        write_export(tmp_path/'invalid.json.gz',{'coefficients':[value]})
