"""Figure generation is separate from numerical map computation."""
import json
from pathlib import Path

import numpy as np
from aiida_empa_orca.maps_data import draw_maps


def main():
    request = json.loads(Path('request.json').read_text())
    with np.load('maps.npz', allow_pickle=False) as arrays:
        draw_maps(arrays, request['metadata'], request['settings'], 'maps.png', 'maps.pdf')


if __name__ == '__main__':
    main()
