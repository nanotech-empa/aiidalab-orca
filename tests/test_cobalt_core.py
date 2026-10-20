"""Native CASSCF Co cores, standalone execution and producing-node identity."""
import io
import json
from importlib.resources import files
from pathlib import Path
import subprocess
import sys

import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca import cobalt_xps as co
from aiida_empa_orca.cobalt_core import CobaltCoreCalculation, CobaltCoreParser, source_calculation
from aiida_empa_orca.scripts.casscf_core import core_reference

FILES = Path(__file__).parent/'fixtures'/'xps_spin'
NATIVE = (FILES/'copc-native-core-excerpt.out').read_text()
NUMBERS = [6]*12+[27]+[6]*20+[1]*16+[7]*8
SOURCE = 'c64ca4a7-a549-465f-b53b-fdaa6956aa49'


def test_native_co_core_assignment_agrees_with_existing_character_parser():
    data = core_reference(NATIVE, NUMBERS, SOURCE)
    characters = co.orbital_characters(NATIVE)
    assert [(r['index'], r['shell']) for r in data['assignments']] == [(0, '1s'), (2, '2p'), (3, '2p'), (4, '2p')]
    for row in data['assignments']:
        assert row['atom_index'] == 12 and row['occupation'] == 2
        assert row['population'] == characters[row['index']]['co_s' if row['shell'] == '1s' else 'co_p']
    assert data['wavefunction_modified'] is False and data['source_calculation_uuid'] == SOURCE
    # The identity is derived from populations/energies, not hardcoded indices.
    changed = NATIVE.replace('0         1         2         3         4         5', '10        11        12        13        14        15')
    assert [r['index'] for r in core_reference(changed, NUMBERS, SOURCE)['assignments']] == [10, 12, 13, 14]


@pytest.mark.parametrize('changed, message', [
    (NATIVE.replace('100.0       0.0       0.0       0.0', '90.0       0.0       0.0       0.0'), 'unambiguous'),
    (NATIVE.replace('2.00000', '1.00000', 1), 'fully occupied'),
    (NATIVE.replace('ORCA TERMINATED NORMALLY', 'error termination in GUESS'), 'terminate normally'),
    (NATIVE.replace('LOEWDIN ORBITAL-COMPOSITIONS', 'missing'), 'Missing native'),
    (NATIVE.replace('12 Co', '11 Co'), 'Invalid native atom'),
    (NATIVE.replace('-283.46283', 'nan'), 'Invalid native orbital'),
])
def test_ambiguous_or_invalid_native_cores_stop(changed, message):
    with pytest.raises(ValueError, match=message):
        core_reference(changed, NUMBERS, SOURCE)


def test_staged_casscf_helper_needs_no_backend_or_wavefunction(tmp_path):
    for name in ('core_orbitals.py', 'casscf_core.py'):
        (tmp_path/name).write_text(files('aiida_empa_orca').joinpath('scripts', name).read_text())
    (tmp_path/'aiida.out').write_text(NATIVE)
    (tmp_path/'request.json').write_text(json.dumps({'kind': 'native_casscf_co', 'numbers': NUMBERS, 'source_calculation_uuid': SOURCE}))
    subprocess.run([sys.executable, '-I', '-S', '-c',
                    "import runpy; runpy.run_path('core_orbitals.py', run_name='__main__')"],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    assert json.loads((tmp_path/'core.json').read_text()) == core_reference(NATIVE, NUMBERS, SOURCE)
    assert not list(tmp_path.glob('*.gbw'))


def make_source(computer):
    structure = orm.StructureData(ase=Atoms(numbers=NUMBERS)).store()
    code = orm.InstalledCode(computer=computer, filepath_executable='/bin/true').store()
    parent = orm.CalcJobNode(process_type=co.CALC_PROCESS)
    for key, value in {'structure': structure, 'code': code, 'stage': orm.Str('spectator').store(),
                       'model': orm.Dict(dict=co.model_settings()).store(),
                       'parent_reference': orm.Dict(dict=json.loads((FILES/'copc-fixed-neutral-reference.json').read_text())).store()}.items():
        parent.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=key)
    parent.store()
    text = (FILES/'copc-fixed-natural-excerpt.out').read_text()
    block = NATIVE.split('****ORCA TERMINATED')[0]
    text = text.replace('LOEWDIN ORBITAL-COMPOSITIONS', block, 1)
    data = co.parse_reference(text, 'spectator', parent.inputs.parent_reference.get_dict(), co.model_settings())
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO(text), 'aiida.out')
    for key, value in {'reference': orm.Dict(dict=data), 'retrieved': retrieved}.items():
        value.base.links.add_incoming(parent, link_type=LinkType.CREATE, link_label=key)
        value.store()
    parent.set_process_state(ProcessState.FINISHED)
    parent.set_exit_status(0)
    return str(parent.uuid)


def test_calcjob_stages_only_native_text_and_checks_provenance(aiida_profile, aiida_localhost, aiida_manager):
    source = orm.load_node(make_source(aiida_localhost))
    b = CobaltCoreCalculation.get_builder()
    b.structure, b.code = source.inputs.structure, source.inputs.code
    b.source_reference, b.source_retrieved = source.outputs.reference, source.outputs.retrieved
    b.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert info.local_copy_list == [(source.outputs.retrieved.uuid, 'aiida.out', 'aiida.out')]
            assert not info.remote_copy_list
            assert info.retrieve_list == ['core.json', 'core.log']
            assert len(info.codes_info) == 1
            assert info.codes_info[0].cmdline_params == ['core_orbitals.py']
            assert json.loads(Path(folder.get_abs_path('request.json')).read_text())['source_calculation_uuid'] == source.uuid
        other = orm.FolderData().store()
        with pytest.raises(ValueError, match='exact spectator'):
            source_calculation(source.inputs.structure, source.outputs.reference, other, source.inputs.code)
        with pytest.raises(ValueError, match='exact spectator'):
            source_calculation(orm.StructureData(ase=Atoms(numbers=NUMBERS)).store(),
                               source.outputs.reference, source.outputs.retrieved, source.inputs.code)
    finally:
        process.close()


@pytest.mark.parametrize('tamper', [False, True])
def test_parser_compares_remote_report_with_original_native_source(aiida_profile, aiida_localhost, tamper):
    source = orm.load_node(make_source(aiida_localhost))
    node = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.cobalt_core')
    for key, value in {'structure': source.inputs.structure, 'code': source.inputs.code,
                       'source_reference': source.outputs.reference, 'source_retrieved': source.outputs.retrieved}.items():
        node.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=key)
    node.store()
    text = source.outputs.retrieved.base.repository.get_object_content('aiida.out')
    data = core_reference(text, NUMBERS, source.uuid)
    if tamper:
        data['assignments'][0]['index'] = 1
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO(json.dumps(data)), 'core.json')
    retrieved.base.links.add_incoming(node, link_type=LinkType.CREATE, link_label='retrieved')
    retrieved.store()
    parser = CobaltCoreParser(node)
    result = parser.parse()
    if tamper:
        assert result.status == 310 and not parser.outputs
    else:
        assert result is None and parser.outputs['core_reference'].get_dict()['source_calculation_uuid'] == source.uuid
