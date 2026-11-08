"""Opt-in bounded H2 tests: real ORCA CalcJobs in disposable AiiDA storage."""
import json
import os
from pathlib import Path
import sys

from aiida import engine, orm
from ase import Atoms
import pytest

from aiida_empa_orca import artifacts, calculation, casci, casscf, common_orbitals, orbital_inspection, parser
from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.reference import ReferenceWorkChain, ReferenceBaseWorkChain, get_reference_builder


@pytest.mark.skipif(not os.environ.get('ORCA_CASSCF_NATIVE_EXECUTABLE'), reason='Native CASSCF test not requested')
@pytest.mark.parametrize('system,mode', [('H2', 'state_specific'), ('H2', 'state_average'), ('NO', 'state_specific')])
def test_h2_optimized_reference_is_inspectable_and_reusable(
        system, mode, aiida_profile_clean, aiida_localhost, entry_points, tmp_path):
    for cls, group, name in [
        (calculation.SinglePointCalculation, 'calculations', 'single_point'),
        (parser.SinglePointParser, 'parsers', 'single_point'),
        (ReferenceBaseWorkChain, 'workflows', 'reference_base'),
        (ReferenceWorkChain, 'workflows', 'reference'),
        (common_orbitals.CommonOrbitalsCalculation, 'calculations', 'common_orbitals'),
        (common_orbitals.CommonOrbitalsParser, 'parsers', 'common_orbitals'),
        (common_orbitals.CommonOrbitalsWorkChain, 'workflows', 'common_orbitals'),
        (casscf.CasscfCalculation, 'calculations', 'casscf'),
        (casscf.CasscfParser, 'parsers', 'casscf'),
        (casscf.CasscfWorkChain, 'workflows', 'casscf'),
        (artifacts.ElectronicStorageCalculation, 'calculations', 'electronic_storage'),
        (artifacts.ElectronicStorageParser, 'parsers', 'electronic_storage'),
        (orbital_inspection.OrbitalCatalogCalculation, 'calculations', 'orbital_catalog'),
        (orbital_inspection.OrbitalCatalogParser, 'parsers', 'orbital_catalog'),
        (orbital_inspection.OrbitalCatalogWorkChain, 'workflows', 'orbital_catalog'),
        (casci.CasciCalculation, 'calculations', 'casci'),
        (casci.CasciParser, 'parsers', 'casci'),
        (casci.CasciWorkChain, 'workflows', 'casci'),
    ]:
        entry_points.add(cls, f'aiida.{group}:empa_orca.{name}')
    from aiida_empa_orca.pdos import OrbitalCharacterCalculation, OrbitalCharacterParser
    entry_points.add(OrbitalCharacterCalculation, 'aiida.calculations:empa_orca.orbital_character')
    entry_points.add(OrbitalCharacterParser, 'aiida.parsers:empa_orca.orbital_character')
    executable = Path(os.environ['ORCA_CASSCF_NATIVE_EXECUTABLE'])
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(executable),
                             prepend_text='export OMP_NUM_THREADS=1\nexport OPENBLAS_NUM_THREADS=1').store()
    export = orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(executable.parent / 'orca_2json')).store()
    worker = tmp_path / 'helper'
    worker.write_text('#!' + sys.executable + '\nimport os,runpy,sys\n'
        'os.environ["OPENBLAS_NUM_THREADS"]="1"\n'
        'assert len(sys.argv)==2 and sys.argv[1] in ("store_electronic.py","compact_orbitals.py","orbital_character.py")\n'
        'runpy.run_path(sys.argv[1],run_name="__main__")\n')
    worker.chmod(0o755)
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable=str(worker)).store()
    helper.base.extras.set('aiidalab_orca_role', 'orbital_character')
    destination = Path(os.environ.get('ORCA_CASSCF_NATIVE_OUTPUT', str(tmp_path / 'report'))) / (system + '-' + mode)
    destination.mkdir(parents=True, exist_ok=True)
    report = {'system': system + ' at fixed geometry', 'scope': 'isolated pytest storage',
              'processes': 1, 'memory_mb': 1024, 'mode': mode, 'stages': {}}

    def run(label, builder):
        result, node = engine.run_get_node(builder)
        report['stages'][label] = {'uuid': str(node.uuid), 'success': node.is_finished_ok, 'exit_message': node.exit_message}
        (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        for child in node.called_descendants:
            if 'retrieved' in child.outputs:
                for name in child.outputs.retrieved.base.repository.list_object_names():
                    if name.endswith(('.out', '.log')):
                        try:
                            (destination / f'{label}-{child.uuid}-{name}').write_text(child.outputs.retrieved.base.repository.get_object_content(name))
                        except (UnicodeError, OSError):
                            pass
        assert node.is_finished_ok, f'{label}: {node.exit_message}; inspect {destination}'
        return str(node.uuid)

    policy = orm.Dict(dict={'threshold_mb': 100, 'stash_directory': str(tmp_path / 'unused')})
    structure = orm.StructureData(ase=Atoms(system, positions=[[0, 0, 0], [0, 0, 1.4 if system == 'H2' else 1.151]]))
    multiplicity = 1 if system == 'H2' else 2
    settings = protocol_settings(overrides={'method': 'PBE', 'basis': 'def2-SVP', 'charge': 0,
        'multiplicity': multiplicity, 'nprocs': 1, 'memory_mb': 1024, 'wallclock_seconds': 600})
    b = get_reference_builder(structure, settings, code)
    b.character_enabled = orm.Bool(False)
    scf_uuid = run('scf', b)
    source = orm.load_node(scf_uuid)
    b = common_orbitals.CommonOrbitalsWorkChain.get_builder()
    b.structure, b.settings, b.code = source.outputs.structure, source.inputs.settings, code
    b.source_retrieved, b.source_remote = source.outputs.retrieved, source.outputs.remote_folder
    b.storage_code, b.storage_policy = helper, policy
    b.character_enabled = orm.Bool(False)
    common_uuid = run('common', b)
    common = orm.load_node(common_uuid)
    original = common.outputs.orbital_reference.get_dict()
    space = {'electrons': 2, 'orbitals': [0, 1]} if system == 'H2' else {'electrons': 3, 'orbitals': [6, 7, 8]}
    values = {'mode': mode, 'states': ([{'multiplicity': multiplicity, 'weights': [1]}] if mode == 'state_specific' else
              [{'multiplicity': 1, 'weights': [2, 1]}, {'multiplicity': 3, 'weights': [1]}])}
    from aiidalab_orca import casscf_services, casci_services
    plan = casscf_services.review(common_uuid, space, values)
    assert plan['action'] == 'compute'
    b = casscf_services.builder(plan)
    b.character_memory_gib = orm.Int(1)
    optimized_uuid = run('casscf', b)
    optimized = orm.load_node(optimized_uuid)
    assert 'casscf' in optimized.outputs.pdos
    assert optimized.outputs.pdos.casscf.metadata.get_dict()['energy_meaning'] == 'none'
    assert casscf_services.review(common_uuid, space, values)['reuse_uuid'] == optimized_uuid
    assert optimized_uuid in [r['uuid'] for r in casci_services.reference_runs(scf_uuid)]
    assert orm.load_node(common_uuid).outputs.orbital_reference.get_dict() == original
    assert optimized.outputs.orbital_reference.uuid != common.outputs.orbital_reference.uuid
    report['casscf'] = optimized.outputs.state_energies.get_dict()
    b = orbital_inspection.OrbitalCatalogWorkChain.get_builder()
    b.orbital_reference, b.source_remote = optimized.outputs.orbital_reference, optimized.outputs.remote_folder
    b.export_code, b.storage_code, b.storage_policy = export, helper, policy
    catalog_uuid = run('catalog', b)
    levels = orm.load_node(catalog_uuid).outputs.catalog.get_dict()['sets']['CASSCF']['levels']
    assert all('energy_ev' not in row for row in levels)
    assert any(1e-4 < row['occupation'] < 1.9999 for row in levels)
    report['occupations'] = levels
    b = casci.CasciWorkChain.get_builder()
    b.orbital_reference, b.source_remote = optimized.outputs.orbital_reference, optimized.outputs.remote_folder
    b.active_space = orm.Dict(dict=space)
    b.settings = orm.Dict(dict={'multiplicity': multiplicity, 'nroots': 1})
    b.code, b.storage_code, b.storage_policy = code, helper, policy
    final_uuid = run('casci', b)
    state = orm.load_node(final_uuid).outputs.state_energies.get_dict()['states'][0]
    assert abs(state['energy_hartree'] - report['casscf']['states'][0]['energy_hartree']) <= 1e-7
    report['casci_state'] = state
    from aiidalab_orca.casscf import CasscfOrbitals
    panel = CasscfOrbitals(common_uuid, space, lambda _: None)
    try:
        assert panel.saved.value == optimized_uuid and not panel.inspect.disabled
        (destination / 'state-energies.svg').write_text(panel.levels.children[1].plot.value)
    finally:
        panel.close()
    from aiida.tools.archive import create_archive
    create_archive([orm.load_node(uuid) for uuid in (scf_uuid, common_uuid, optimized_uuid, catalog_uuid, final_uuid)],
                   filename=destination / 'casscf-pipeline.aiida')
    (destination / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
