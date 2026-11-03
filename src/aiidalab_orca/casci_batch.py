"""Review independent charge/spin requests before any CASCI submission."""

import html
import re

from aiida_empa_orca import casci
from .presentation import data_table


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


def prepare_batch(reference_uuid, electrons, norb, charges, multiplicities, values, force=False):
    from . import casci_services as service
    reference = service.reference_data(reference_uuid)
    space, rows = sector_requests(reference,electrons,norb,charges,multiplicities,values['nroots'])
    running = [row for row in service.runs(reference_uuid)
               if row['state'] in ('created','running','waiting')]
    for row in rows:
        if row['status'] == 'skip':
            continue
        settings = dict(values,charge=row['charge'],multiplicity=row['multiplicity'],nroots=row['nroots'])
        try:
            checked = casci.casci_settings(settings,reference,space)
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
            plan = service.prepare_casci(reference_uuid,electrons,norb,settings,force)
            row.update(status=plan['action'],plan=plan)
            if plan['action'] == 'reuse':
                row['uuid'] = plan['reuse_uuid']
        except (ValueError,KeyError,OSError,RuntimeError) as exc:
            row.update(status='blocked',reason=str(exc))
    return {'kind':'casci-batch','reference_uuid':reference_uuid,'active_space':space,'rows':rows,
            'resources':{name:values[name] for name in ('nprocs','memory_mb','wallclock_seconds')},
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
    return (f'<p><b>{count} new calculations; {reuse} reused; {running} already running; '
            f'{skipped} incompatible combinations skipped.</b></p>'
            +target+
            f'<p>Per new calculation: {resources["nprocs"]} processes, {resources["memory_mb"]} MiB total memory, '
            f'{resources["wallclock_seconds"]//60} minutes wall time. New calculations may run concurrently. '
            'All use the same fixed geometry and spatial-orbital reference. '
            'Review any reduction in the number of states before submitting.</p>'
            +table+previews)
