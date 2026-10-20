"""Exchange calculation executed by the configured Dyson tools CalcJob."""
import json
from pathlib import Path

from aiida_empa_orca.kondo_data import exchange


def main():
    request = json.loads(Path('request.json').read_text())
    report = exchange(request['table'], request['parameters'])
    Path('channels.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print('Computed', len(report['channels']), 'Kondo eigenchannels')


if __name__ == '__main__':
    main()
