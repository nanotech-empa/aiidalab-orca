"""Isolated source-plane sampling and constant-height Dyson intensity maps.

Vacuum propagation follows meqpy's Dyson.extrapolate_wavefunction, itself
adapted from cp2k-spm-tools: each in-plane Fourier component decays with
sqrt(k_parallel**2 + kappa**2). See MAPS_LICENSE.txt for attribution.
"""
import math

import numpy as np
from ase.units import Bohr
from scipy.ndimage import map_coordinates

from .dyson_data import blend_options, blend_weight, spin_factor


def plane_basis(normal):
    """Match the shared slice viewer's right-handed in-plane coordinate frame."""
    n = np.asarray(normal, dtype=float)
    if n.shape != (3,) or not np.isfinite(n).all() or np.linalg.norm(n) < 1e-12:
        raise ValueError('Specify a finite, nonzero plane normal')
    n = n / np.linalg.norm(n)
    trial = [1., 0., 0.] if abs(n[0]) < .9 else [0., 1., 0.]
    u = np.cross(n, trial)
    u /= np.linalg.norm(u)
    return n, u, np.cross(n, u)


def map_parameters(values):
    keys = {'plane', 'heights_angstrom', 'kappa_inv_angstrom', 'padding', 'transition_ids', 'channel_ids',
            'kind', 'spin_convention', 'blend'}
    if set(values) - keys:
        raise ValueError('Unknown map settings')
    p = dict(values)
    kondo = 'channel_ids' in p
    if kondo:
        if 'transition_ids' in p or 'spin_convention' in p or 'blend' in p or p.get('kind', 'individual') != 'individual':
            raise ValueError('Kondo channel maps are individual unit-normalized orbitals; no spectral blend or extra spin factor')
        p['kind'] = 'individual'
    plane = dict(p['plane'])
    if set(plane) != {'center', 'normal', 'offset', 'width', 'height', 'resolution'}:
        raise ValueError('Incomplete map plane')
    center = np.asarray(plane['center'], dtype=float)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError('The reference point must have three finite coordinates')
    plane_basis(plane['normal'])
    plane.update(center=center.tolist(), normal=np.asarray(plane['normal'], dtype=float).tolist())
    for key in ('offset', 'width', 'height'):
        if not isinstance(plane[key], (int, float)) or not math.isfinite(plane[key]):
            raise ValueError('Plane dimensions must be finite')
    if min(plane['width'], plane['height']) <= 0:
        raise ValueError('Plane width and height must be positive')
    if type(plane['resolution']) is not int or not 32 <= plane['resolution'] <= 512:
        raise ValueError('Map resolution must be 32–512 points per axis')
    heights = p['heights_angstrom']
    if (not isinstance(heights, list) or not 1 <= len(heights) <= 8 or
            any(not isinstance(h, (int, float)) or not math.isfinite(h) or h < plane['offset'] for h in heights) or
            len(set(heights)) != len(heights)):
        raise ValueError('Choose 1–8 distinct observation heights at or beyond the source slice')
    if not isinstance(p['kappa_inv_angstrom'], (int, float)) or not 0 < p['kappa_inv_angstrom'] <= 10:
        raise ValueError('Use a positive finite vacuum decay constant, at most 10 Å⁻¹')
    if type(p['padding']) is not int or not 0 <= p['padding'] <= 512:
        raise ValueError('FFT padding must be 0–512 pixels per edge')
    ids = p['channel_ids' if kondo else 'transition_ids']
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 32 or
            any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids)):
        raise ValueError('Select 1–32 unique transitions')
    if p['kind'] not in ('individual', 'blend') or (not kondo and p['spin_convention'] not in ('unpolarized', 'highest_ms_component')):
        raise ValueError('Select individual maps or a blend and an explicit spin convention')
    if p['kind'] == 'blend':
        p['blend'] = blend_options(p['blend'])
        if p['blend']['spin_convention'] != p['spin_convention']:
            raise ValueError('Map and spectral spin conventions differ')
    else:
        p.pop('blend', None)
    panels = len(ids) if p['kind'] == 'individual' else 1
    if len(heights) * panels * plane['resolution']**2 > 32_000_000:
        raise ValueError('Reduce the resolution, heights or number of panels')
    p['plane'] = plane
    return p


def default_plane(positions, width, height, resolution=128):
    positions = np.asarray(positions, dtype=float)
    center = (positions.min(axis=0) + positions.max(axis=0)) / 2
    center[2] = positions[:, 2].max()
    return dict(center=center.tolist(), normal=[0., 0., 1.], offset=1.5,
                width=float(width), height=float(height), resolution=resolution)


def sample_source(cube, plane):
    """Interpolate amplitudes inside the full cube; never repeat or fill missing data."""
    n, u, v = plane_basis(plane['normal'])
    x = np.linspace(-plane['width']/2, plane['width']/2, plane['resolution'])
    y = np.linspace(-plane['height']/2, plane['height']/2, plane['resolution'])
    xx, yy = np.meshgrid(x, y)
    origin = np.asarray(plane['center']) + plane['offset'] * n
    xyz = origin + xx[..., None] * u + yy[..., None] * v
    spacing = np.asarray(cube['spacing'])
    index = (xyz - cube['origin']) @ np.linalg.inv(spacing)
    maximum = np.asarray(cube['data'].shape) - 1
    if np.any(index < -1e-7) or np.any(index > maximum + 1e-7):
        raise ValueError('Source plane extends outside the full cube. Reduce its size or change its position; no vacuum data were invented.')
    index = np.clip(index, 0, maximum)
    data = map_coordinates(cube['data'], np.moveaxis(index, -1, 0), order=1, mode='constant',
                           cval=np.nan, prefilter=False)
    if not np.isfinite(data).all():
        raise ValueError('Source slice contains missing or nonfinite amplitudes')
    # Match meqpy: convert the cube's Bohr^(-3/2) amplitudes to Å^(-3/2).
    return data / Bohr**1.5, x, y


def propagate(source, x, y, distances, kappa, padding=0):
    """Fourier vacuum propagation of amplitudes, followed by cropping of padding."""
    data = np.pad(source, padding)
    ky = 2*np.pi*np.fft.fftfreq(data.shape[0], d=y[1]-y[0])
    kx = 2*np.pi*np.fft.rfftfreq(data.shape[1], d=x[1]-x[0])
    decay = np.sqrt(ky[:, None]**2 + kx[None, :]**2 + kappa**2)
    fourier = np.fft.rfft2(data)
    for distance in distances:
        if not math.isfinite(distance) or distance < 0:
            raise ValueError('Vacuum propagation only supports heights beyond the source plane')
        wave = np.fft.irfft2(fourier * np.exp(-distance*decay), s=data.shape)
        yield wave[padding:-padding, padding:-padding] if padding else wave


def compute_maps(cubes, table, parameters):
    """Read one amplitude cube at a time; never extrapolate an intensity blend."""
    p = map_parameters(parameters)
    kondo = 'channel_ids' in p
    ids = p['channel_ids' if kondo else 'transition_ids']
    rows = {r['id']: r for r in table['channels' if kondo else 'transitions']}
    if not set(ids) <= rows.keys():
        raise ValueError('A selected transition is absent from the source Dyson result')
    count = len(ids) if p['kind'] == 'individual' else 1
    result = np.zeros((len(p['heights_angstrom']), count, p['plane']['resolution'], p['plane']['resolution']))
    distances = np.asarray(p['heights_angstrom']) - p['plane']['offset']
    sources = []
    from ase.io.cube import read_cube
    for j, identifier in enumerate(ids):
        with open(cubes[identifier]) as handle:
            cube = read_cube(handle)
        source, x, y = sample_source(cube, p['plane'])
        row = rows[identifier]
        weight = (1. if kondo else blend_weight(row, table['initial_state']['multiplicity'], p['blend']) if p['kind'] == 'blend'
                  else spin_factor(table['initial_state']['multiplicity'], row['final_multiplicity'], p['spin_convention']))
        for h, wave in enumerate(propagate(source, x, y, distances, p['kappa_inv_angstrom'], p['padding'])):
            result[h, j if p['kind'] == 'individual' else 0] += weight * wave**2
        if kondo:
            sources.append(dict(channel_id=identifier, intensity_multiplier=1., coupling=row['coupling'],
                exchange_over_v2_inv_ev=row['exchange_over_v2_inv_ev'], degenerate_channels=row['degenerate_channels']))
            continue
        sources.append(dict(transition_id=identifier, intensity_multiplier=weight,
                            energy_ev=row.get('energy_ev'), final_charge=row.get('final_charge'),
                            final_multiplicity=row['final_multiplicity'], final_root=row.get('final_root'),
                            side=row.get('side'), component_strength=row['strength'],
                            selected_strength=row['strength']*spin_factor(table['initial_state']['multiplicity'], row['final_multiplicity'], p['spin_convention'])))
    n, u, v = plane_basis(p['plane']['normal'])
    units = 'angstrom^-3'
    if p['kind'] == 'blend' and p['blend']['mode'] == 'energy':
        units += ' eV^-1'
    metadata = dict(schema_version=1, parameters=p, units=units, sources=sources,
                    plane_frame=dict(reference_point=p['plane']['center'], normal=n.tolist(), u=u.tolist(), v=v.tolist()),
                    minimum=float(result.min()), maximum=float(result.max()),
                    panels=ids if p['kind'] == 'individual' else ['spectral_blend'],
                    model='meqpy Fourier vacuum propagation; spin-free s-tip intensity; no absolute current calibration')
    metadata['panel_labels'] = ([] if kondo else [f"{r.get('side') or r['transition_id']} r{r.get('final_root')} · M={r['final_multiplicity']}\n"
                                 f"W={r['selected_strength']:.3f}" for r in sources]
                                if p['kind'] == 'individual' else ['Spectral blend'])
    if kondo:
        metadata.update(observable='kondo_channel_intensity',
            model='individual normalized Kondo eigenchannel; s-tip Fourier vacuum propagation; no NRG spectral weight',
            parameters=p, warnings=table['warnings'], chemical_potential_ev=table['parameters']['chemical_potential_ev'])
        metadata['panel_labels'] = [f"{r['channel_id']} · {r['coupling']}\nj/V²={r['exchange_over_v2_inv_ev']:.3f} eV⁻¹" for r in sources]
    return dict(intensity=result, u_angstrom=x, v_angstrom=y,
                heights_angstrom=np.asarray(p['heights_angstrom'])), metadata


def figure_style(values):
    p = {'vmin': 0., 'cmap': 'bone', 'dpi': 300, 'scale_bar_angstrom': 5., 'rotation': 0} | values
    if set(p) != {'vmin', 'vmax', 'cmap', 'dpi', 'scale_bar_angstrom', 'rotation'}:
        raise ValueError('Unknown or incomplete figure style')
    if not np.isfinite([p['vmin'], p['vmax'], p['scale_bar_angstrom']]).all() or not 0 <= p['vmin'] < p['vmax']:
        raise ValueError('Choose an explicit increasing, nonnegative shared intensity range')
    if p['cmap'] not in ('bone', 'gray', 'viridis', 'magma') or p['rotation'] not in (0, 90, 180, 270):
        raise ValueError('Unsupported colour map or panel rotation')
    if type(p['dpi']) is not int or not 72 <= p['dpi'] <= 600 or p['scale_bar_angstrom'] < 0:
        raise ValueError('Use 72–600 DPI and a nonnegative scale bar length')
    return p


def draw_maps(arrays, metadata, style, png, pdf):
    """One fixed colour range for every panel; no per-image normalization."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import Normalize
    p = figure_style(style)
    data = arrays['intensity']
    x, y = arrays['u_angstrom'], arrays['v_angstrom']
    data = np.rot90(data, p['rotation']//90, axes=(-2, -1))
    if p['rotation'] in (90, 270):
        x, y = y, x
    spanx, spany = np.ptp(x), np.ptp(y)
    if p['scale_bar_angstrom'] >= min(spanx, spany):
        raise ValueError('The scale bar must be shorter than the map dimensions')
    nr, nc = data.shape[:2]
    ratio = spany/spanx
    if max(2*nc, 2*ratio*nr)*p['dpi'] > 12000:
        raise ValueError('Reduce figure DPI, panel count or aspect ratio')
    fig, axes = plt.subplots(nr, nc, figsize=(2*nc, 2*ratio*nr), squeeze=False,
                             layout='constrained')
    norm = Normalize(p['vmin'], p['vmax'])
    for i in range(nr):
        for j in range(nc):
            ax = axes[i, j]
            image = ax.imshow(data[i, j], origin='lower', extent=[x[0], x[-1], y[0], y[-1]],
                              cmap=p['cmap'], norm=norm, aspect='equal', interpolation='nearest')
            ax.set_xticks([])
            ax.set_yticks([])
            if i == 0:
                ax.set_title(metadata.get('panel_labels', metadata['panels'])[j], fontsize=9)
            if j == 0:
                ax.set_ylabel(f"{arrays['heights_angstrom'][i]:g} Å", fontsize=9)
            if p['scale_bar_angstrom']:
                x0, y0 = x[0]+.08*spanx, y[0]+.08*spany
                ax.plot([x0, x0+p['scale_bar_angstrom']], [y0, y0], color='white', lw=2)
                ax.text(x0+p['scale_bar_angstrom']/2, y0+.03*spany,
                        f"{p['scale_bar_angstrom']:g} Å", color='white', fontsize=7, ha='center')
    unit_label = r'$\mathrm{\AA}^{-3}$'
    if metadata['units'].endswith('eV^-1'):
        unit_label += r' $\mathrm{eV}^{-1}$'
    fig.colorbar(image, ax=axes.ravel().tolist(), label=unit_label, shrink=.65)
    fig.savefig(png, dpi=p['dpi'])
    fig.savefig(pdf, dpi=p['dpi'])
    plt.close(fig)
