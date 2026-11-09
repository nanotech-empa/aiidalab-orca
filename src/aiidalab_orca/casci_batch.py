"""Review independent charge/spin requests before any CASCI submission."""

import html
import re

from aiida_empa_orca import casci
from .presentation import data_table
from .resources import memory_label


def parse_integer_list(text, name, *, positive=False):
    pattern = r'\s*[+-]?[0-9]+(?:(?:\s*,\s*|\s+)[+-]?[0-9]+)*\s*'
    if not re.fullmatch(pattern, text):
        raise ValueError(f'Enter {name} as integers separated by spaces or commas.')
    values = list(dict.fromkeys(int(value) for value in re.findall(r'[+-]?[0-9]+', text)))
    if positive and any(value < 1 for value in values):
        raise ValueError('Multiplicities must be positive integers: 1=singlet, 2=doublet, 3=triplet, …')
    return values


def sector_requests(reference, electrons, norb, charges, multiplicities, roots):
    """Keep every requested pair visible, including reasons for impossible pairs."""
    if type(roots) is not int or roots < 1:
        raise ValueError('Request at least one electronic state per allowed sector.')
    start = (reference['n_electrons']-electrons)//2
    space = casci.active_space({'electrons':electrons,'orbitals':list(range(start,start+norb))},reference)
    rows = []
    for charge in charges:
        count = electrons-charge+reference['charge']
        for mult in multiplicities:
            row = {'charge':charge,'multiplicity':mult,'active_electrons':count,
                   'requested_roots':roots,'nroots':0,'status':'skip','reason':''}
            if not 0 <= count <= 2*norb:
                row['reason'] = f'{count} active electrons do not fit in {norb} orbitals (0–{2*norb}).'
            elif (count-(mult-1)) % 2:
                row['reason'] = 'Electron count and spin multiplicity have incompatible parity.'
            else:
                dimension = casci.spin_sector_dimension(norb,count,mult)
                if not dimension:
                    row['reason'] = 'This spin exceeds the capacity of the active space.'
                else:
                    row.update(status='ready',dimension=dimension,nroots=min(roots,dimension))
                    if roots > dimension:
                        row['reason'] = (f'Requested {roots} states; this sector contains {dimension} '
                                         +('state.' if dimension == 1 else 'states.'))
            rows.append(row)
    return space, rows


def prepare_batch(reference_uuid, electrons, norb, charges, multiplicities, values, force=False,
                  *, native_output_policy=None):
    from . import casci_services as service
    reference = service.reference_data(reference_uuid)
    active_batch = service.active_casci_batch(reference_uuid)
    space, rows = sector_requests(reference,electrons,norb,charges,multiplicities,values['nroots'])
    running = [row for row in service.runs(reference_uuid)
               if row['state'] in ('created','running','waiting')]
    for row in rows:
        if row['status'] == 'skip':
            continue
        settings = dict(values,charge=row['charge'],multiplicity=row['multiplicity'],nroots=row['nroots'])
        try:
            checked = casci.casci_settings(settings,reference,space)
            row['settings'] = checked
            if active_batch:
                row.update(status='blocked',reason='Wait for the active serial batch '+active_batch)
                continue
            current = None
            if not force:
                for run in running:
                    if (run['space'] == space and
                            casci.casci_settings(run['settings'],reference,space) == checked):
                        current = run
                        break
            if current:
                row.update(status='running',uuid=current['uuid'])
                continue
            options = {'native_output_policy': native_output_policy} if native_output_policy is not None else {}
            plan = service.prepare_casci(reference_uuid,electrons,norb,settings,force,**options)
            row.update(status=plan['action'],plan=plan)
            if plan['action'] == 'reuse':
                row['uuid'] = plan['reuse_uuid']
        except (ValueError,KeyError,OSError,RuntimeError) as exc:
            row.update(status='blocked',reason=str(exc))
    return {'kind':'casci-batch','active_batch_uuid':active_batch,'reference_uuid':reference_uuid,'active_space':space,'rows':rows,
            'resources':{name:values[name] for name in ('nprocs','memory_mb','wallclock_seconds')},
            'native_output_policy': native_output_policy,
            'ready':any(row['status'] in ('compute','reuse','running') for row in rows) and
                    not any(row['status'] == 'blocked' for row in rows)}


def review_html(plan, execution=None):
    rows = plan['rows']
    count = sum(row['status'] == 'compute' for row in rows)
    reuse = sum(row['status'] == 'reuse' for row in rows)
    running = sum(row['status'] == 'running' for row in rows)
    skipped = sum(row['status'] == 'skip' for row in rows)
    resources = plan['resources']
    labels = {'compute':'New calculation','reuse':'Reuse saved calculation',
              'running':'Already running','skip':'Skip','blocked':'Blocked'}
    table = data_table(['Charge','Active electrons','Multiplicity','Requested states','States to use','Action','Reason'],[
        [
        f'{row["charge"]:+d}',row['active_electrons'],row['multiplicity'],
        row['requested_roots'],row['nroots'] or '—',labels[row['status']],row['reason']]
        for row in rows],numeric_columns=range(5),label='Requested charge and spin combinations')
    previews = ''.join(f'<details><summary>Input: charge {row["charge"]:+d}, multiplicity '
        f'{row["multiplicity"]}</summary><pre>'+html.escape(row['plan']['input'])+'</pre></details>'
        for row in rows if 'plan' in row)
    target = (f'<p><b>Execution target:</b> {html.escape(execution["code"])}@'
              f'{html.escape(execution["computer"])} — inherited from the orbital reference.</p>' if execution else '')
    policy = plan.get('native_output_policy')
    retention = ''
    if policy:
        retention = ('Stash full logs and wavefunctions at ' + html.escape(policy['stash_directory'])
                     if policy['mode'] == 'stash' else 'Leave full logs and wavefunctions on the calculation computer')
        maximum = policy.get('maxsizeoutput', 5 * 1024**2) / 1024**2
        retention = ('<p><b>Full files for new calculations:</b> '+retention+
                     f'. Native text output up to {maximum:g} MiB is retrieved unchanged; larger output uses a validation extract. '
                     'Reused/running results keep their recorded retention.</p>')
    return (f'<p><b>{count} new calculations; {reuse} reused; {running} already running; '
            f'{skipped} incompatible combinations skipped.</b></p>'
            +target+
            f'<p>Per new calculation: {resources["nprocs"]} processes, {memory_label(resources["memory_mb"])} total memory, '
            f'{resources["wallclock_seconds"]//60} minutes wall time. Sectors run sequentially, one at a time, in a persistent AiiDA batch. '
            'Each sector waits for the previous workflow and its CalcJobs to terminate, including failures. '
            'A submission error stops the remaining queue without automatic retries. '
            'All use the same fixed geometry and spatial-orbital reference. '
            'Review any reduction in the number of states before submitting.</p>'
            +retention+table+previews)
