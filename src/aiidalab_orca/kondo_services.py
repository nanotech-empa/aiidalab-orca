"""Operation-local access to Kondo calculations; widgets retain UUIDs only."""
from pathlib import PurePosixPath
from aiida import orm
from aiida.engine import submit

from aiida_empa_orca import kondo
from aiida_empa_orca.kondo_data import exchange, parameters
from aiida_empa_orca.orbitals import cube_parameters
from .casci_services import progress


def history(transitions_uuid):
    rows = []
    for uuid in kondo.previous(transitions_uuid, 'transitions', kondo.PROCESS):
        node = orm.load_node(uuid)
        mu = node.inputs.parameters.get_dict()['chemical_potential_ev']
        rows.append((f'μ={mu:g} eV · {node.process_state.value} · {str(uuid)[:8]}', str(uuid)))
    return rows


def prepare(transitions_uuid, mu, code_uuid):
    node = orm.load_node(transitions_uuid)
    kondo.source(node)
    p = parameters(dict(chemical_potential_ev=mu), node.get_dict())
    report = exchange(node.get_dict(), p)
    if not code_uuid:
        raise ValueError('Configure Dyson tools')
    return dict(transitions_uuid=str(transitions_uuid), code_uuid=str(code_uuid), parameters=p,
                warnings=report['warnings'], stability_interval_ev=report['stability_interval_ev'])


def submit_channels(plan):
    checked = prepare(plan['transitions_uuid'], plan['parameters']['chemical_potential_ev'], plan['code_uuid'])
    b = kondo.KondoWorkChain.get_builder()
    b.transitions = orm.load_node(checked['transitions_uuid'])
    b.parameters = orm.Dict(dict=checked['parameters'])
    b.code = orm.load_code(checked['code_uuid'])
    b.metadata.label = 'Kondo orbitals · μ='+str(checked['parameters']['chemical_potential_ev'])+' eV'
    return str(submit(b).uuid)


def result(uuid):
    n = orm.load_node(uuid)
    if not n.is_finished_ok or n.process_type != kondo.PROCESS:
        raise ValueError('Select successful Kondo orbitals')
    return dict(channels_uuid=str(n.outputs.channels.uuid), data=n.outputs.channels.get_dict())


def cube_history(channels_uuid):
    return [(str(uuid)[:8], str(uuid)) for uuid in kondo.previous(channels_uuid, 'channels', kondo.CUBES_PROCESS)]


def native_plot_code(channels_uuid):
    """Match the initial CASCI's ORCA installation, without guessing versions."""
    dyson = kondo.channel_source(orm.load_node(channels_uuid))
    state = dyson.inputs.artifacts.initial.creator.inputs.state_energies
    source = state.creator.inputs.code
    expected = PurePosixPath(source.filepath_executable).with_name('orca_plot')
    matches = []
    for uuid in orm.QueryBuilder().append(orm.InstalledCode,project=['uuid']).all(flat=True):
        code = orm.load_code(uuid)
        if code.computer.uuid == source.computer.uuid and PurePosixPath(code.filepath_executable) == expected:
            matches.append(str(uuid))
    if len(matches) != 1:
        raise ValueError('Configure one ORCA plot code from the same installation as the initial CASCI code.')
    return matches[0]


def submit_cubes(channels_uuid, values, code_uuid, cubehandler_uuid, *, plot_uuid=None):
    b = kondo.KondoCubesWorkChain.get_builder()
    b.channels = orm.load_node(channels_uuid)
    b.parameters = orm.Dict(dict=cube_parameters(values))
    b.code, b.cubehandler_code = orm.load_code(code_uuid), orm.load_code(cubehandler_uuid)
    b.plot_code = orm.load_code(plot_uuid or native_plot_code(channels_uuid))
    b.metadata.label = 'Kondo orbital cubes'
    return str(submit(b).uuid)
