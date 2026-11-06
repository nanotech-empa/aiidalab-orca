"""Opt-in purpose-made allyl geometry → default PDOS → QRO/UNO → CASCI test.

Uses installed licensed ORCA, one process per job, and isolated pytest storage.
Set ORCA_PDOS_NATIVE_EXECUTABLE to orca and ORCA_PDOS_PIPELINE_OUTPUT to a private
directory to retain a review report and AiiDA archive. Nothing is installed.
"""
import json
import os
from pathlib import Path
import sys

from aiida import engine, orm
from ase import Atoms
import numpy as np
import pytest

from aiida_empa_orca import artifacts, calculation, casci, common_orbitals, parser, pdos
from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.reference import ReferenceWorkChain
from aiida_empa_orca.workchains import GeometryWorkChain, OptimizationBaseWorkChain, get_builder
from aiidalab_orca.pdos_data import molecular_normal, p_perpendicular


@pytest.mark.skipif(not os.environ.get('ORCA_PDOS_NATIVE_EXECUTABLE'), reason='Native ORCA pipeline not requested')
def test_new_allyl_reference_has_automatic_character_and_inspectable_CASCI(
        aiida_profile_clean, aiida_localhost, entry_points, tmp_path):
    registrations = [
        (calculation.OptimizationCalculation, 'aiida.calculations:empa_orca.optimization'),
        (parser.OptimizationParser, 'aiida.parsers:empa_orca.optimization'),
        (OptimizationBaseWorkChain, 'aiida.workflows:empa_orca.base'),
        (GeometryWorkChain, 'aiida.workflows:empa_orca.geometry'),
        (ReferenceWorkChain, 'aiida.workflows:empa_orca.reference'),
        (pdos.OrbitalCharacterCalculation, 'aiida.calculations:empa_orca.orbital_character'),
        (pdos.OrbitalCharacterParser, 'aiida.parsers:empa_orca.orbital_character'),
        (common_orbitals.CommonOrbitalsCalculation, 'aiida.calculations:empa_orca.common_orbitals'),
        (common_orbitals.CommonOrbitalsParser, 'aiida.parsers:empa_orca.common_orbitals'),
        (common_orbitals.CommonOrbitalsWorkChain, 'aiida.workflows:empa_orca.common_orbitals'),
        (artifacts.ElectronicStorageCalculation, 'aiida.calculations:empa_orca.electronic_storage'),
        (artifacts.ElectronicStorageParser, 'aiida.parsers:empa_orca.electronic_storage'),
        (casci.CasciCalculation, 'aiida.calculations:empa_orca.casci'),
        (casci.CasciParser, 'aiida.parsers:empa_orca.casci'),
        (casci.CasciWorkChain, 'aiida.workflows:empa_orca.casci')]
    for cls, name in registrations:
        entry_points.add(cls, name)
    destination = Path(os.environ.get('ORCA_PDOS_PIPELINE_OUTPUT', str(tmp_path / 'report')))
    destination.mkdir(parents=True, exist_ok=True)
    executable = Path(os.environ['ORCA_PDOS_NATIVE_EXECUTABLE'])
    orca = orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(executable),
        prepend_text='export OMP_NUM_THREADS=1\nexport OPENBLAS_NUM_THREADS=1').store()
    orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(executable.parent / 'orca_2json')).store()

    def worker(name, allowed):
        path = tmp_path / name
        path.write_text('#!' + sys.executable + '\nimport os,runpy,sys\n'
            'os.environ["OPENBLAS_NUM_THREADS"]="1"\nos.environ["OMP_NUM_THREADS"]="1"\n'
            f'assert len(sys.argv)==2 and sys.argv[1] in {allowed!r}\n'
            'runpy.run_path(sys.argv[1],run_name="__main__")\n')
        path.chmod(0o755)
        return orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(path)).store()
    helper = worker('orbital-character', ['orbital_character.py'])
    helper.base.extras.set('aiidalab_orca_role', 'orbital_character')
    storage = worker('orbital-storage', ['store_electronic.py'])
    policy = orm.Dict(dict={'threshold_mb': 100, 'stash_directory': str(tmp_path / 'unused-stash')})
    atoms = Atoms('C3H5', positions=[[-1.2, 0, 0], [0, .7, 0], [1.2, 0, 0],
        [-2.15, .5, 0], [-1.2, -1.08, 0], [0, 1.8, 0], [2.15, .5, 0], [1.2, -1.08, 0]])
    settings = protocol_settings(overrides={'method': 'PBE', 'basis': 'def2-SVP',
        'charge': 0, 'multiplicity': 2, 'nprocs': 1, 'memory_mb': 1024, 'wallclock_seconds': 600})
    report = {'system': 'allyl radical C3H5', 'profile_scope': 'isolated pytest storage',
              'settings': settings, 'stages': {}, 'orbital_character': {}}
    uuids = []

    def run_stage(label, b):
        b.metadata.label = 'Allyl PDOS/CASCI test · ' + label
        outputs, node = engine.run_get_node(b)
        uuids.append(str(node.uuid))
        report['stages'][label] = {'uuid': str(node.uuid), 'success': node.is_finished_ok,
                                 'exit_message': node.exit_message}
        (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if not node.is_finished_ok:
            print(label, node.exit_message)
            for child in node.called_descendants:
                if child.is_failed and 'retrieved' in child.outputs:
                    for name in ('aiida.out', 'export.log', 'character.log', 'storage.log'):
                        try:
                            print(name, child.outputs.retrieved.base.repository.get_object_content(name)[-4000:])
                        except OSError:
                            pass
        assert node.is_finished_ok
        return str(node.uuid)

    b = get_builder(orm.StructureData(ase=atoms), settings, orca, force_recompute=True)
    b.character_memory_gib = orm.Int(2)
    geometry_uuid = run_stage('optimized_doublet', b)
    geometry = orm.load_node(geometry_uuid)
    assert geometry.outputs.pdos_status['state'] == 'ready'
    report['geometry_energy_hartree'] = geometry.outputs.optimization_summary['energy_hartree']
    (destination / 'optimized.xyz').write_text('\n'.join([str(len(atoms)), 'Optimized allyl doublet PBE/def2-SVP'] +
        [f'{s} {p[0]:.12f} {p[1]:.12f} {p[2]:.12f}' for s, p in
         zip(geometry.outputs.structure.get_ase().symbols, geometry.outputs.structure.get_ase().positions)]) + '\n')

    b = common_orbitals.CommonOrbitalsWorkChain.get_builder()
    b.structure, b.settings, b.code = geometry.outputs.structure, geometry.inputs.settings, orca
    b.source_retrieved, b.source_remote = geometry.outputs.retrieved, geometry.outputs.remote_folder
    b.storage_code, b.storage_policy = storage, policy
    b.character_memory_gib = orm.Int(2)
    common_uuid = run_stage('common_orbitals', b)
    common = orm.load_node(common_uuid)
    assert common.outputs.pdos_status['state'] == 'ready'
    ref = common.outputs.orbital_reference.get_dict()
    start = (ref['n_electrons'] - 3) // 2
    selected = list(range(start, start + 3))

    for owner_uuid, kind in ((geometry_uuid, 'SCF'), (common_uuid, 'QRO'), (common_uuid, 'UNO')):
        owner = orm.load_node(owner_uuid)
        data = owner.outputs.pdos[kind.lower()]
        metadata = data.metadata.get_dict()
        arrays = {name: data.character.get_array(name) for name in data.character.get_arraynames()}
        normal, _ = molecular_normal([a['Coords'] for a in metadata['atoms']])
        pi = p_perpendicular(arrays, [0, 1, 2], normal)
        np.savez_compressed(destination / (kind.lower() + '-character.npz'), **arrays)
        (destination / (kind.lower() + '-metadata.json')).write_text(json.dumps(metadata, indent=2) + '\n')
        report['orbital_character'][kind] = {'selected_indices': selected,
            'perpendicular_p': [float(pi[i]) for i in selected],
            'occupations': [float(arrays['occupations'][i]) for i in selected],
            'channels': metadata['channels']}
        if kind == 'QRO':
            # Reject a chemically different contiguous window instead of running CAS blindly.
            (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            assert all(pi[i] > .75 for i in selected), report['orbital_character'][kind]

    b = casci.CasciWorkChain.get_builder()
    b.orbital_reference, b.source_remote = common.outputs.orbital_reference, common.outputs.remote_folder
    b.active_space = orm.Dict(dict={'electrons': 3, 'orbitals': selected})
    b.settings = orm.Dict(dict={'charge': 0, 'multiplicity': 2, 'nroots': 3,
                              'nprocs': 1, 'memory_mb': 1024, 'wallclock_seconds': 600})
    b.code, b.storage_code, b.storage_policy = orca, storage, policy
    casci_uuid = run_stage('CAS_3_3_doublet_3_roots', b)
    report['casci'] = orm.load_node(casci_uuid).outputs.state_energies.get_dict()
    from aiida.tools.archive import create_archive
    create_archive([orm.load_node(uuid) for uuid in uuids], filename=destination / 'allyl-pdos-casci.aiida')
    (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    from aiidalab_orca import pdos_services
    from aiidalab_orca.pdos import PdosPanel
    assert pdos_services.latest(geometry_uuid, 'SCF')['metadata']['channels'] == ['alpha', 'beta']
    panel = PdosPanel(common_uuid, kind='QRO')
    assert panel.record and panel.compute.description == 'Refresh saved PDOS'
    panel.close()
