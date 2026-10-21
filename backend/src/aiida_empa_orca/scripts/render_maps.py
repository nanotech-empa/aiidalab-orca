"""Figure generation is separate from numerical map computation."""
import json
from pathlib import Path

import numpy as np
from aiida_empa_orca.maps_data import draw_maps


def figure_metadata(metadata):
    """Keep the actual chemical potential attached to exported Kondo panels."""
    if metadata.get('observable') != 'kondo_channel_intensity':
        return metadata
    mu = metadata['chemical_potential_ev']
    labels = metadata.get('panel_labels',metadata['panels'])
    return dict(metadata,panel_labels=[label+f'\nμ={mu:.2f} eV' for label in labels])


def main():
    request = json.loads(Path('request.json').read_text())
    with np.load('maps.npz', allow_pickle=False) as arrays:
        draw_maps(arrays, figure_metadata(request['metadata']), request['settings'], 'maps.png', 'maps.pdf')


if __name__ == '__main__':
    main()
