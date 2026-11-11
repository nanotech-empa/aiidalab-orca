"""Operation-local access to Kondo calculations; widgets retain UUIDs only."""
from pathlib import PurePosixPath
from aiida import orm
from aiida.engine import submit

from aiida_empa_orca import kondo
from aiida_empa_orca.kondo_data import exchange, parameters
from aiida_empa_orca.orbitals import cube_parameters
from aiida_empa_orca.rendering import helper_resources
from .analysis_execution import assert_idle
from .casci_services import progress


def chemical_potential_context(transitions_uuid):
    """Read immutable charging energies without retaining a node in the UI."""
    from .kondo_guidance import charging_context
    return charging_context(orm.load_node(transitions_uuid).get_dict())


def history(transitions_uuid):
    rows = []
    for uuid in kondo.previous(transitions_uuid, 'transitions', kondo.PROCESS):
        node = orm.load_node(uuid)
        mu = node.inputs.parameters.get_dict()['chemical_potential_ev']
        rows.append((f'μ={mu:g} eV · {node.process_state.value} · {str(uuid)[:8]}', str(uuid)))
    return rows


def prepare(transitions_uuid, mu, code_uuid, *, resources=None):
    node = orm.load_node(transitions_uuid)
    kondo.source(node)
    p = parameters(dict(chemical_potential_ev=mu), node.get_dict())
    report = exchange(node.get_dict(), p)
    if not code_uuid:
        raise ValueError('Configure Dyson tools')
    return dict(transitions_uuid=str(transitions_uuid), code_uuid=str(code_uuid), parameters=p,
                warnings=report['warnings'], stability_interval_ev=report['stability_interval_ev'],
                resources=helper_resources(resources,default_seconds=600))


def channels_builder(plan):
    checked = prepare(plan['transitions_uuid'], plan['parameters']['chemical_potential_ev'], plan['code_uuid'],
                      resources=plan.get('resources'))
    b = kondo.KondoWorkChain.get_builder()
    b.transitions = orm.load_node(checked['transitions_uuid'])
    b.parameters = orm.Dict(dict=checked['parameters'])
    b.code = orm.load_code(checked['code_uuid'])
    b.channel_resources = orm.Dict(dict=checked['resources'])
    b.metadata.label = 'Kondo orbitals · μ='+str(checked['parameters']['chemical_potential_ev'])+' eV'
    return b


def submit_channels(plan):
    assert_idle(orm.load_node(plan['transitions_uuid']).get_dict().get('orbital_reference_uuid'))
    return str(submit(channels_builder(plan)).uuid)


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


def prepare_cubes(channels_uuid, values, code_uuid, cubehandler_uuid, *, plot_uuid=None,
                  resources=None, reference_resources=None):
    channel=kondo.channel_source(orm.load_node(channels_uuid))
    artifact=channel.inputs.artifacts.initial.get_dict()
    p=cube_parameters(values)
    if not p['orbitals'] or p['spin_density']:
        raise ValueError('Select Kondo channel amplitudes')
    if not code_uuid or not cubehandler_uuid:
        raise ValueError('Configure Dyson tools and cubehandler')
    return dict(channels_uuid=str(channels_uuid),parameters=p,code_uuid=str(code_uuid),
                cubehandler_uuid=str(cubehandler_uuid),plot_uuid=str(plot_uuid or native_plot_code(channels_uuid)),
                resources=helper_resources(resources,default_seconds=600),reference_resources=helper_resources(reference_resources,default_seconds=600),
                reference_orbitals=artifact['identity']['active_space']['orbitals'])


def cubes_builder(plan):
    b = kondo.KondoCubesWorkChain.get_builder()
    b.channels = orm.load_node(plan['channels_uuid'])
    b.parameters = orm.Dict(dict=cube_parameters(plan['parameters']))
    b.code, b.cubehandler_code = orm.load_code(plan['code_uuid']), orm.load_code(plan['cubehandler_uuid'])
    b.plot_code = orm.load_code(plan['plot_uuid'])
    b.cube_resources = orm.Dict(dict=helper_resources(plan['resources']))
    b.reference_resources = orm.Dict(dict=helper_resources(plan['reference_resources']))
    b.metadata.label = 'Kondo orbital cubes'
    return b


def submit_reviewed_cubes(plan):
    assert_idle(orm.load_node(plan['channels_uuid']).get_dict().get('orbital_reference_uuid'))
    return str(submit(cubes_builder(plan)).uuid)


def submit_cubes(channels_uuid, values, code_uuid, cubehandler_uuid, *, plot_uuid=None,
                 resources=None,reference_resources=None):
    return submit_reviewed_cubes(prepare_cubes(channels_uuid,values,code_uuid,cubehandler_uuid,
        plot_uuid=plot_uuid,resources=resources,reference_resources=reference_resources))
