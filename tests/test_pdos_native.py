"""Optional native export qualification in isolated AiiDA storage, never live install.

Set ORCA_PDOS_NATIVE_FIXTURE to a directory with aiida.gbw/source.json/source.out
and ORCA_PDOS_EXPORT_EXECUTABLE to the installed native orca_2json executable.
The fixture is supplied privately; no licensed binaries or wavefunctions ship.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import numpy as np
import pytest
from aiida import engine, orm
from ase import Atoms

from aiida_empa_orca.pdos import OrbitalCharacterCalculation, OrbitalCharacterParser


@pytest.mark.skipif(not os.environ.get('ORCA_PDOS_NATIVE_FIXTURE'), reason='Native ORCA fixture not requested')
def test_native_export_and_ORCA_Lowdin_populations(aiida_profile, aiida_localhost, entry_points, tmp_path):
    root = Path(os.environ['ORCA_PDOS_NATIVE_FIXTURE'])
    source = json.loads((root / 'source.json').read_text())
    entry_points.add(OrbitalCharacterCalculation, 'aiida.calculations:empa_orca.orbital_character')
    entry_points.add(OrbitalCharacterParser, 'aiida.parsers:empa_orca.orbital_character')
    export = orm.InstalledCode(computer=aiida_localhost,
        filepath_executable=os.environ['ORCA_PDOS_EXPORT_EXECUTABLE']).store()
    wrapper = tmp_path / 'orca-character'
    wrapper.write_text('#!' + sys.executable + '\nimport os,runpy,sys\n'
        'os.environ["OPENBLAS_NUM_THREADS"]="1"\nos.environ["OMP_NUM_THREADS"]="1"\n'
        'assert sys.argv[1:]==["orbital_character.py"]\n'
        'runpy.run_path("orbital_character.py",run_name="__main__")\n')
    wrapper.chmod(0o755)
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(wrapper)).store()
    folder = orm.FolderData()
    filename = source['file']['name']
    folder.base.repository.put_object_from_file(root / 'aiida.gbw', 'electronic/' + filename)
    folder.store()
    structure = orm.StructureData(ase=Atoms(source['symbols'], positions=source['positions']))
    b = OrbitalCharacterCalculation.get_builder()
    b.code, b.helper_code, b.source = export, helper, folder
    b.source_remote = orm.RemoteData(computer=aiida_localhost, remote_path=str(root))
    b.structure = structure
    b.identity = orm.Dict(dict={'source_uuid': source['source_uuid'], 'kind': source.get('kind', 'SCF'), 'filename': filename,
        'charge': source['charge'], 'multiplicity': source['multiplicity']})
    b.location = orm.Dict(dict={'kind': 'repository', 'uuid': str(folder.uuid), 'files': [source['file']]})
    b.metadata.options = {'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 1},
                           'max_wallclock_seconds': 600, 'max_memory_kb': 2 * 1024**2}
    outputs, process = engine.run_get_node(b)
    if not process.is_finished_ok:
        for name in ['export.log', 'character.log']:
            try:
                print(name, process.outputs.retrieved.base.repository.get_object_content(name)[-5000:])
            except (AttributeError, OSError):
                pass
    assert process.is_finished_ok
    metadata = outputs['metadata'].get_dict()
    arrays = {name: outputs['character'].get_array(name) for name in outputs['character'].get_arraynames()}
    difference = None
    if source.get('kind', 'SCF') == 'SCF':
        native = (root / 'source.out').read_text()
        rows = re.search(r'LOEWDIN ATOMIC CHARGES AND SPIN POPULATIONS\s*\n-+\n(.*?)(?:\n\s*\n)', native, re.S)[1]
        reference = np.array([[float(q), float(s)] for q, s in re.findall(
            r'\d+\s+[A-Z][a-z]?\s*:\s*([-\d.]+)\s+([-\d.]+)', rows)])
        occupied = arrays['weights'].sum(axis=2) * arrays['occupations'][:, None]
        charge = np.array([a['ElementNumber'] for a in metadata['atoms']]) - occupied.sum(axis=0)
        spin = occupied[arrays['spin'] == 0].sum(axis=0) - occupied[arrays['spin'] == 1].sum(axis=0)
        np.testing.assert_allclose(charge, reference[:, 0], atol=6e-7, rtol=0)
        np.testing.assert_allclose(spin, reference[:, 1], atol=6e-7, rtol=0)
        difference = float(max(abs(charge - reference[:, 0]).max(), abs(spin - reference[:, 1]).max()))
    result = {'process_uuid': str(process.uuid), 'profile_scope': 'isolated pytest storage',
        'source_uuid_in_live_profile': source['source_uuid'], 'metadata': metadata,
        'native_population_max_difference': difference,
        'source_wavefunction_sha256': hashlib.sha256((root / 'aiida.gbw').read_bytes()).hexdigest()}
    destination = root / 'qualified'
    destination.mkdir(exist_ok=True)
    (destination / 'metadata.json').write_text(json.dumps(result, indent=2) + '\n')
    np.savez_compressed(destination / 'character.npz', **arrays)
    with process.outputs.retrieved.base.repository.open('export.log', mode='rb') as handle:
        (destination / 'export.log').write_bytes(handle.read())
