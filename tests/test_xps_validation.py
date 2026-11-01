"""Regression checks for native core-hole convergence and saved-density audits."""
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest
from aiida import common, orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca import xps
from aiida_empa_orca.scripts.xps_validation import (
    density_summary, gradient_check, parse_spin_density, validate_stage,
)

FILES = Path(__file__).parent/'fixtures'/'xps_spin'
REFERENCE = json.loads((FILES/'reference.json').read_text())
CORE = json.loads((FILES/'no-core.json').read_text())


def test_xps_operating_guide_is_packaged_for_shared_chat_agents():
    from importlib.resources import files
    from aiidalab_orca.xps_guidance import workflow_guides
    guide, = workflow_guides()
    assert guide['id'] == 'orca.xps'
    assert guide['text'] == files('aiidalab_orca').joinpath('knowledge/xps.md').read_text()
    assert 'Contract for agents in the AiiDAlab chat' in guide['text']
    assert 'not permission' in guide['text']
    metadata = tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())
    assert metadata['project']['entry-points']['aiidalab_assistant.workflow_guides']['orca_xps'] == 'aiidalab_orca.xps_guidance:workflow_guides'
    assert 'knowledge/*.md' in metadata['tool']['setuptools']['package-data']['aiidalab_orca']


@pytest.mark.parametrize('electrons,spin,frontier,multiplicity', [
    (291, 'alpha', 144, 1), (291, 'beta', 143, 3),
    (253, 'alpha', 125, 1), (253, 'beta', 124, 3),
])
def test_compact_configuration_preserves_the_requested_density(electrons, spin, frontier, multiplicity):
    preparation, refinement, check = xps.strict_stage_parameters(
        REFERENCE['settings'], 5, spin, electrons, 'freeze_release')
    scf = preparation['input_blocks']['scf']
    channel = 0 if spin == 'alpha' else 1
    assert preparation['charge'] == 1 and preparation['multiplicity'] == multiplicity
    assert scf['AlphaConf' if channel == 0 else 'BetaConf'] == '0,1'
    assert scf['Rotate'] == f'\n {{5,{frontier},90,{channel},{channel}}}\nend'
    assert 'IonizeAlpha' not in scf and 'IonizeBeta' not in scf
    assert 'FreezeAndRelease' in preparation['input_keywords']
    assert refinement['input_blocks']['scf']['DirectResetFreq'] == 1
    assert refinement['input_blocks']['scf']['TolG'] == 1e-6
    assert 'FreezeAndRelease' not in refinement['input_keywords']
    assert 'AlphaConf' not in refinement['input_blocks']['scf']
    assert 'BetaConf' not in refinement['input_blocks']['scf']
    assert 'Rotate' not in refinement['input_blocks']['scf']
    assert {'NoIter', 'CalcGuessEnergy'} <= set(check['input_keywords'])
    assert check['input_blocks']['scf'] == {'MaxIter': 0}


def test_native_scf_success_does_not_override_a_failed_final_gradient():
    # Actual native NO output says SCF converged, but its final gradient is
    # 5.98e-5 with a requested 1e-5. It must not pass the new strict contract.
    text = (FILES/'no-1-alpha.out').read_text()
    assert density_summary(text)['energy_hartree'] < 0
    with pytest.raises(ValueError, match='final orbital gradient'):
        gradient_check(text, 1e-5)
    earlier = 'Last Orbital Gradient ... 1e-8 Tolerance : 1e-5\n'
    with pytest.raises(ValueError, match='final orbital gradient'):
        gradient_check(earlier+text, 1e-5)


def test_strict_native_identity_and_normalization_checks():
    text = (FILES/'no-0-alpha.out').read_text()
    result = parse_spin_density(text, CORE, 0, 15, REFERENCE['ground_energy_hartree'],
                                2, 'alpha', strict=True)
    assert result['hole_population'] > .99
    for bad, message in [(text+'\nPOORLY NORMALIZED MO DETECTED', 'normalized'),
                         (text+'\nUsing GuessMode=CMatrix', 'CMatrix'),
                         (text.replace('Input basis set matches current basis set', 'mismatch'), 'basis mismatch')]:
        with pytest.raises(ValueError, match=message):
            parse_spin_density(bad, CORE, 0, 15, REFERENCE['ground_energy_hartree'],
                               2, 'alpha', strict=True)


def test_atom_identity_cannot_mislabel_a_co_2p_hole_as_1s(monkeypatch):
    # Synthetic unit case: one atom, occupied 1s below an empty 2p orbital.
    # Real Co calculations can collapse between these shells while retaining
    # their target atom and spin count. No energy result is fabricated here.
    import aiida_empa_orca.scripts.xps_validation as validation
    channels = [[{'index': 0, 'occupation': 1., 'energy_hartree': -200.},
                 {'index': 1, 'occupation': 0., 'energy_hartree': -30.}],
                [{'index': 0, 'occupation': 1., 'energy_hartree': -200.}]]
    monkeypatch.setattr(validation, '_orbital_readers', lambda: (
        lambda text: channels, lambda *args, **kwargs: [{0:[1.], 1:[1.]}, {0:[1.]}]))
    text = ('SCF CONVERGED AFTER 3 CYCLES\nORCA TERMINATED NORMALLY\n'
            'Input Geometry matches current geometry\nInput basis set matches current basis set\n'
            'FINAL SINGLE POINT ENERGY -99\nExpectation value of <S**2> : 1\n')
    with pytest.raises(ValueError, match='another shell'):
        parse_spin_density(text, {'assignments':[{'atomic_populations':[1.]}], 'method':'unit'},
                           0, 3, -100., 2, 'alpha', strict=True)


def test_inactive_freeze_release_cannot_be_polished():
    text = (FILES/'no-0-alpha.out').read_text()
    request = {'core_reference': CORE, 'atom_index': 0, 'electron_count':15,
               'ground_energy_hartree':REFERENCE['ground_energy_hartree'],
               'spin_channel':'alpha', 'scf_convergence':'TightSCF', 'solver':'freeze_release'}
    with pytest.raises(ValueError, match='did not activate'):
        validate_stage(text+'\nNo orbitals to constrain!', request, 'preparation')


def test_readback_requires_an_actual_energy_evaluation():
    # These are deliberate mutations testing the guard, not native results.
    text = (FILES/'no-0-alpha.out').read_text()
    text = re.sub(r'SCF (?:CONVERGED AFTER|NOT CONVERGED)', 'removed SCF marker', text)
    text += '\nMaxIter==0 has been chosen - skipping the SCF\n'
    with pytest.raises(ValueError, match='CalcGuessEnergy'):
        density_summary(text, require_scf=False)
    assert density_summary(text+'\n! NoIter CalcGuessEnergy', require_scf=False)['energy_hartree'] < 0


def test_finalizer_stops_before_orca_when_preparation_failed(tmp_path):
    from importlib.resources import files
    for script in ('core_orbitals.py', 'xps_validation.py', 'xps_finalize.py'):
        (tmp_path/script).write_text(files('aiida_empa_orca').joinpath('scripts', script).read_text())
    (tmp_path/'xps_request.json').write_text(json.dumps({'orca_executable':'/must-not-run'}))
    (tmp_path/'preparation.out').write_text('ORCA finished by error termination in SCF\n')
    # Supply the request fields used before native termination is inspected.
    request = {'core_reference':CORE,'atom_index':0,'electron_count':15,
               'ground_energy_hartree':REFERENCE['ground_energy_hartree'],
               'spin_channel':'alpha','orca_executable':'/must-not-run'}
    (tmp_path/'xps_request.json').write_text(json.dumps(request))
    result = subprocess.run([sys.executable, '-I', '-S', 'xps_finalize.py'], cwd=tmp_path,
                             capture_output=True, text=True)
    assert result.returncode != 0 and 'did not terminate normally' in result.stderr
    assert not (tmp_path/'aiida.out').exists()
    assert not (tmp_path/'xps_validation.json').exists()


def test_three_stages_run_serially_and_retrieve_only_validation_text(aiida_profile, aiida_localhost, aiida_manager):
    structure = orm.StructureData(ase=Atoms(numbers=REFERENCE['numbers'], positions=REFERENCE['positions']))
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    repository = orm.FolderData()
    repository.base.repository.put_object_from_filelike(io.BytesIO(b'placeholder'), 'electronic/aiida.gbw')
    repository.base.repository.put_object_from_filelike(io.StringIO(
        f'SCF CONVERGED AFTER 12 CYCLES\nFINAL SINGLE POINT ENERGY {REFERENCE["ground_energy_hartree"]}\nORCA TERMINATED NORMALLY\n'), 'aiida.out')
    repository.store()
    b = xps.XpsSiteCalculation.get_builder()
    b.structure, b.settings, b.code = structure, orm.Dict(dict=REFERENCE['settings']), code
    b.source_retrieved, b.core_reference, b.atom_index = repository, orm.Dict(dict=CORE), orm.Int(0)
    b.source_repository, b.source_filename = repository, orm.Str('aiida.gbw')
    b.helper_code, b.strict_validation, b.solver = helper, orm.Bool(True), orm.Str('freeze_release')
    b.metadata.options.resources = {'num_machines':1,'num_mpiprocs_per_machine':4}
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert info.codes_run_mode == common.CodeRunMode.SERIAL
            assert [c.cmdline_params for c in info.codes_info] == [['preparation.inp'], ['xps_finalize.py']]
            for name, source in [('preparation', 'reference'), ('aiida', 'preparation'), ('wavefunction_check', 'aiida')]:
                assert f'%moinp "{source}.gbw"' in Path(folder.get_abs_path(name+'.inp')).read_text()
            assert all(not name.endswith('.gbw') for name in info.retrieve_list)
            assert 'wavefunction_check.out' in info.retrieve_list and 'xps_validation.json' in info.retrieve_list
    finally:
        process.close()
