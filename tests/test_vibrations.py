"""Real ORCA 6.1.1 Hessian, optical adapter and provenance-reuse contracts."""

import io
from pathlib import Path

import ase.io
import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import vibrations as backend
from aiida_empa_orca.protocols import protocol_settings

FIXTURE = Path(__file__).parent/'fixtures'/'vibrations'


def data():
    atoms = ase.io.read(FIXTURE/'h2co.xyz')
    arrays, summary = backend.parse_vibrations((FIXTURE/'h2co.out').read_text(),
        (FIXTURE/'h2co.hess').read_text(), atoms, True)
    return atoms, arrays, summary


def record():
    atoms, arrays, summary = data()
    return {'uuid': 'workflow', 'data_uuid': 'arrays', 'summary': summary,
            'symbols': atoms.get_chemical_symbols(), 'positions': atoms.positions.tolist(),
            'arrays': {key: value.tolist() for key, value in arrays.items()}}


def test_real_hessian_units_order_and_origin():
    atoms, arrays, summary = data()
    assert summary['number_of_modes'] == 6 and not summary['imaginary_mode_indices']
    assert summary['frequency_scaling'] == 1
    assert summary['hessian_origin_shift_angstrom'][2] == pytest.approx(.60881447)
    assert arrays['frequencies'][6:] == pytest.approx([1199.85987, 1269.26341, 1533.00330, 1896.71771, 2901.73309, 2967.28569])
    assert arrays['ir_intensities'][9] == pytest.approx(114.78430181)
    assert arrays['raman_activities'][10] == pytest.approx(188.161594)
    assert arrays['displacements'].shape == (12, 4, 3)
    # Recentring the input is harmless; a distortion or rotation must not pass
    # without transforming every response tensor and displacement as well.
    atoms.translate([3, 1, 5])
    backend.parse_vibrations((FIXTURE/'h2co.out').read_text(), (FIXTURE/'h2co.hess').read_text(), atoms, True)
    atoms.positions[0, 0] += .05
    with pytest.raises(ValueError, match='coordinates'):
        backend.parse_vibrations((FIXTURE/'h2co.out').read_text(), (FIXTURE/'h2co.hess').read_text(), atoms, True)


@pytest.mark.parametrize('replacement', ['termination', 'tensor', 'missing'])
def test_invalid_scientific_output_is_rejected(replacement):
    text, hess = (FIXTURE/'h2co.out').read_text(), (FIXTURE/'h2co.hess').read_text()
    if replacement == 'termination':
        text = text.replace('ORCA TERMINATED NORMALLY', '')
    elif replacement == 'tensor':
        hess = hess.replace('-1.5630400216E+00', '-9.5630400216E+00')
    else:
        text = text.replace('RAMAN SPECTRUM', 'MISSING TABLE')
    with pytest.raises(ValueError):
        backend.parse_vibrations(text, hess, ase.io.read(FIXTURE/'h2co.xyz'), True)


def test_molecular_optics_use_orca_activities_and_cartesian_tensors():
    from aiidalab_orca.vibration_viewer import MolecularResponse
    response = MolecularResponse(record(), activity=True)
    parallel, crossed, frequencies, _ = response.run_powder_raman_intensities(frequency_laser=532, temperature=300)
    np.testing.assert_allclose(parallel+crossed, response.arrays['raman_activities'][6:])
    np.testing.assert_allclose(crossed/parallel, response.arrays['depolarizations'][6:])
    # The out-of-plane mode 6 has an xz Raman tensor in this yz molecular plane.
    kwargs = {'pol_incoming': [0, 0, 1], 'frequency_laser': 532, 'temperature': 300}
    x, _, _ = response.run_single_crystal_raman_intensities(pol_outgoing=[1, 0, 0], **kwargs)
    y, _, _ = response.run_single_crystal_raman_intensities(pol_outgoing=[0, 1, 0], **kwargs)
    assert x[0] > 1 and y[0] < 1e-8
    response.activity = False
    assert not np.allclose(response.prefactor(532, 300), response.prefactor(633, 300), rtol=1e-3, atol=0)
    for vector in ([0, 0, 0], [float('nan'), 0, 1]):
        with pytest.raises(ValueError):
            response.polarization(vector)
    with pytest.raises(ValueError):
        response.prefactor(532, -1)


def test_adapter_reuses_qe_viewer_and_mode_participation():
    from aiidalab_orca.vibration_viewer import MolecularRamanModel, MolecularSpectrum
    from aiidalab_qe_vibroscopy.app.widgets.ramanwidget import RamanWidget
    assert issubclass(MolecularSpectrum, RamanWidget)
    model = MolecularRamanModel(record())
    model.input_structure = ase.io.read(FIXTURE/'h2co.xyz')
    model.spectrum_type, model.vibrational_data_uuid = 'Raman', 'arrays'
    model.fetch_data()
    model.update_data()
    np.testing.assert_allclose(model._atom_participation.sum(axis=1), np.ones(6))
    model.selected_atoms = '1..4'
    model.update_data()
    np.testing.assert_allclose(model.projected_intensities, model.intensities)
    model.separate_polarizations = True
    model.update_data()
    np.testing.assert_allclose(model.projected_intensities, model.intensities)
    np.testing.assert_allclose(model.projected_depolarized, model.intensities_depolarized)
    assert max(model.intensities+model.intensities_depolarized) == pytest.approx(1)
    model.broadening = 0
    with pytest.raises(ValueError, match='Broadening'):
        model.update_data()


def test_frequency_submission_does_not_optimize_or_retrieve_wfn(aiida_profile, aiida_localhost, aiida_manager):
    settings = protocol_settings(overrides={'charge': 0, 'multiplicity': 1})
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    builder = backend.VibrationsCalculation.get_builder()
    builder.structure = orm.StructureData(ase=ase.io.read(FIXTURE/'h2co.xyz'))
    builder.code, builder.maxcore_mb = code, orm.Int(768)
    builder.parameters = orm.Dict(dict=backend.frequency_parameters(settings))
    builder.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 2}
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            text = Path(folder.get_abs_path('aiida.inp')).read_text()
            assert 'AnFreq' in text and 'Polar 1' in text and 'Opt' not in text
            assert info.retrieve_list == ['aiida.out', 'aiida.hess']
    finally:
        process.close()


def test_reuse_survives_scratch_loss_and_force_recompute(aiida_profile_clean, aiida_localhost, tmp_path):
    from aiidalab_orca import vibration_services as service
    from aiida_empa_orca.reuse import PROCESS_TYPE as GEO
    atoms, arrays, summary = data()
    structure = orm.StructureData(ase=atoms).store()
    settings = orm.Dict(dict=protocol_settings(overrides={'charge': 0, 'multiplicity': 1})).store()
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    source = orm.WorkChainNode(process_type=GEO)
    for name, value in {'structure': structure, 'settings': settings, 'code': code, 'optimize': orm.Bool(True).store()}.items():
        source.base.links.add_incoming(value, link_type=LinkType.INPUT_WORK, link_label=name)
    source.store()
    calc = orm.CalcJobNode().store()
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO('optimized'), 'aiida.out')
    remote = orm.RemoteData(computer=aiida_localhost, remote_path=str(tmp_path/'deleted-scratch'))
    for name, value in {'retrieved': retrieved, 'remote_folder': remote,
                        'optimization_summary': orm.Dict(dict={'converged': True}), 'output_parameters': orm.Dict(dict={})}.items():
        value.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label=name)
        value.store()
        value.base.links.add_incoming(source, link_type=LinkType.RETURN, link_label=name)
    structure.base.links.add_incoming(source, link_type=LinkType.RETURN, link_label='structure')
    source.set_process_state(ProcessState.FINISHED)
    source.set_exit_status(0)
    initial = service.prepare(str(source.uuid))
    assert initial['reuse_uuid'] is None
    previous = orm.WorkChainNode(process_type=backend.PROCESS_TYPE)
    for name, value in {'structure': structure, 'settings': settings, 'code': code, 'raman': orm.Bool(True).store(),
                        'source_retrieved': retrieved}.items():
        previous.base.links.add_incoming(value, link_type=LinkType.INPUT_WORK, link_label=name)
    previous.store()
    producer = orm.CalcJobNode().store()
    data_node = orm.ArrayData()
    for name, value in arrays.items():
        data_node.set_array(name, value)
    stored = orm.FolderData()
    stored.base.repository.put_object_from_filelike(io.StringIO((FIXTURE/'h2co.out').read_text()), 'aiida.out')
    hessian = orm.SinglefileData(file=FIXTURE/'h2co.hess')
    for name, value in {'vibrational_data': data_node, 'summary': orm.Dict(dict=summary), 'hessian': hessian, 'retrieved': stored}.items():
        value.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label=name)
        value.store()
        value.base.links.add_incoming(previous, link_type=LinkType.RETURN, link_label=name)
    previous.set_process_state(ProcessState.FINISHED)
    previous.set_exit_status(0)
    plan = service.prepare(str(source.uuid))
    assert plan['reuse_uuid'] == str(previous.uuid)
    assert service.prepare(str(source.uuid), force_recompute=True)['reuse_uuid'] is None
    assert service.prepare(str(source.uuid), raman=False)['reuse_uuid'] == str(previous.uuid)
    builder = backend.VibrationsWorkChain.get_builder()
    builder.structure, builder.settings, builder.code = structure, settings, code
    builder.source_retrieved, builder.reuse_uuid = retrieved, orm.Str(previous.uuid)
    for name in backend.OUTPUTS:
        builder.reuse[name] = previous.outputs[name]
    outputs, reused = run_get_node(builder)
    assert reused.is_finished_ok and not reused.called_descendants
    assert outputs['hessian'].uuid == hessian.uuid
