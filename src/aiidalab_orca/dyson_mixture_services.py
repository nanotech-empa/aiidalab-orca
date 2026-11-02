"""Operation-local access to explicit initial-state population mixtures."""
from aiida import orm

from aiida_empa_orca import dyson
from aiida_empa_orca.dyson_mixture import MIXTURE_PROCESS, checked_sources, combine_dyson


def candidates(state_rows):
    results,seen = [],set()
    for state_uuid in sorted({r['state_uuid'] for r in state_rows}):
        for uuid in dyson.previous(state_uuid,'initial',dyson.DYSON_PROCESS):
            run = orm.load_node(uuid)
            if not run.is_finished_ok or 'transitions' not in run.outputs:
                continue
            node = run.outputs.transitions
            if str(node.uuid) in seen:
                continue
            seen.add(str(node.uuid))
            table = node.get_dict()
            initial = table['initial_state']
            results.append(dict(uuid=str(node.uuid), **initial, count=len(table['transitions']),
                label=f"q={initial['charge']:+d} · mult {initial['multiplicity']} · root {initial['root']} · "
                      f"{len(table['transitions'])} transitions · {run.ctime:%Y-%m-%d %H:%M} · {str(uuid)[:8]}"))
    return results


def review(populations):
    """Return only serialized data; keep nodes local to this operation."""
    sources = {'s'+str(i):orm.load_node(uuid) for i,uuid in enumerate(populations)}
    weights = {'s'+str(i):p for i,p in enumerate(populations.values())}
    table = checked_sources(sources,weights)
    return dict(populations=dict(populations),initial_states=table['initial_states'],
                transition_count=len(table['transitions']))


def save(plan):
    populations = plan['populations']
    sources = {'s'+str(i):orm.load_node(uuid) for i,uuid in enumerate(populations)}
    weights = {'s'+str(i):p for i,p in enumerate(populations.values())}
    result = combine_dyson(orm.Dict(dict=weights), **sources,
        metadata={'label':'Dyson initial-state population mixture · actual transition energies'})
    return str(result['transitions'].creator.uuid)


def history(state_rows):
    allowed = {r['state_uuid'] for r in state_rows}
    rows = orm.QueryBuilder().append(orm.CalcFunctionNode,tag='run',
        filters={'process_type':MIXTURE_PROCESS,'attributes.exit_status':0},project=['uuid']).order_by(
        {'run':{'ctime':'desc'}}).all(flat=True)
    results = []
    for uuid in rows:
        run = orm.load_node(uuid)
        if 'transitions' not in run.outputs:
            continue
        states = run.outputs.transitions.get_dict().get('initial_states',[])
        if states and {r['state_uuid'] for r in states} <= allowed:
            weights = ' / '.join(f"M{r['multiplicity']} r{r['root']}: {r['population']:g}" for r in states)
            results.append((f'{weights} · {run.ctime:%Y-%m-%d %H:%M} · {str(uuid)[:8]}',str(uuid)))
    return results
