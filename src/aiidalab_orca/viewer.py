"""Molecular trajectory and convergence display from serialized results."""

import base64
import html
import io

import ipywidgets as ipw
import matplotlib.pyplot as plt
import nglview as nv
from ase import Atoms


def settings_details(settings, *, single_point=False):
    """Expose the full effective specification, including expert overrides."""
    from aiida_empa_orca.protocols import PROTOCOLS, editable_settings, protocol_overrides, reference, approximation
    s = editable_settings(settings)
    label = PROTOCOLS[s["protocol"]]["label"] if settings.get("schema_version") == 2 else "Legacy geometry settings"
    basis = s["basis"] + (" + element overrides" if s["element_settings"] else "")
    text = f"{s['method']}/{basis} · {reference(s)} · {approximation(s)}"
    changes = protocol_overrides(s)
    if single_point:
        for key in ("optimization", "max_geometry_steps", "constraints"):
            changes.pop(key, None)
    from aiida_empa_orca.constraints import describe_constraints
    constraints = describe_constraints(s.get("constraints", []))
    constraint_text = ("<p><b>Geometry constraints:</b><br>" + "<br>".join(html.escape(c) for c in constraints) + "</p>"
                       if constraints else "<p>Geometry constraints: none.</p>")
    if single_point:
        constraint_text = "<p>Single-point SCF at fixed atomic positions.</p>"
        s = {k: v for k, v in s.items() if k not in ("optimization", "max_geometry_steps")}
    rows = "".join(f"<tr><th style='text-align:left;padding-right:15px'>{html.escape(key.replace('_', ' ').capitalize())}</th><td>{html.escape(str(value))}</td></tr>"
                   for key, value in s.items() if key not in ("schema_version", "protocol", "constraints"))
    return (f"<p><b>{html.escape(text)}</b></p><p>Starting protocol: {html.escape(label)}. "
            f"Changes: {html.escape(', '.join(k.replace('_', ' ') for k in changes) or 'none')}.</p>"
            f"{constraint_text}<details><summary>Effective calculation settings</summary><table>{rows}</table></details>")


def input_details(files, title="Submitted ORCA input"):
    if not files:
        return ""
    entries = []
    for name, content in files.items():
        encoded = base64.b64encode(content.encode()).decode()
        entries.append(f'<h4>{html.escape(name)}</h4><a download="{html.escape(name)}" href="data:text/plain;base64,{encoded}">Download {html.escape(name)}</a>'
                       f"<pre style='max-height:300px;overflow:auto'>{html.escape(content)}</pre>")
    return f"<details><summary>{html.escape(title)}</summary>{''.join(entries)}</details>"


def molecule(symbols, frames):
    trajectory = [Atoms(symbols, positions=positions) for positions in frames]
    view = nv.show_asetraj(trajectory)
    view.clear_representations()
    view.add_ball_and_stick()
    view.background = "#f5f7fa"
    view.layout = ipw.Layout(width="100%", height="360px")
    view.center()
    # A slight camera tilt avoids viewing the NO test molecule end-on along z.
    # This changes only the camera, never the stored coordinates.
    view.control.rotate([0, 0.3826834324, 0, 0.9238795325])
    # NGL already provides playback and a frame slider. Keep a single control.
    view.frame = len(frames)-1
    return view


def show_result(data):
    s = data["settings"]
    scf = data.get("single_point", False)
    title = "Optimized geometry" if data["optimized"] else "Supplied geometry · no optimization performed"
    if scf:
        title = "Single-point SCF · fixed geometry"
    if data["optimized"] and s.get("constraints"):
        title = "Geometry optimized with constraints"
    items = [ipw.HTML(f"<h3>{title}</h3>")]
    provenance = f"<p>{html.escape(data['source_description'])}</p>"
    for warning in data.get("warnings", []):
        items.append(ipw.HTML(f"<p style='color:#a02020'>{html.escape(warning)}</p>"))
    if data.get("source_uuid"):
        kind = "electronic state" if scf else "optimization"
        items.append(ipw.HTML(f"<p><b>Reused an available {kind}.</b> No new ORCA calculation was needed.</p>"))
        provenance += f"<p>Source workflow: <code>{data['source_uuid']}</code></p>"
    if "summary" in data:
        summary = data["summary"]
        basis = s["basis"] + (" + element overrides" if s.get("element_settings") else "")
        text = (f"{s['method']}/{basis} · charge {s['charge']} · multiplicity {s['multiplicity']}"
                f" · converged · E = {summary['energy_hartree']:.9f} Hartree")
        if "spin_squared" in summary:
            text += f" · ⟨S²⟩ = {summary['spin_squared']:.5f}"
        items.append(ipw.HTML(f"<p><b>{html.escape(text)}</b></p>"))
    if data["optimized"] or scf:
        items.append(ipw.HTML(settings_details(s, single_point=scf) + input_details(data.get("input_files", {}))))
    if data.get("levels"):
        from .levels import EnergyLevels
        energy_view = EnergyLevels(data["levels"])
        items.append(energy_view)
        from .orbitals import OrbitalProperties
        properties = ipw.Accordion(children=[ipw.VBox()], selected_index=None)
        def open_properties(change):
            if change["new"] == 0 and not isinstance(properties.children[0], OrbitalProperties):
                properties.children[0].close()
                properties.children = [OrbitalProperties(data, energy_view)]
        properties.observe(open_properties, names="selected_index")
        properties.set_title(0, "Orbitals and spin density")
        items.append(properties)
    if data.get("artifact_status"):
        items.append(ipw.HTML(f"<p><b>Electronic files:</b> {html.escape(data['artifact_status'])}</p>"))
    if "positions" in data:
        if len(data.get("frames", [])) > 1:
            items.append(ipw.HTML("<p>Showing the final geometry. Move the pointer over the molecule to play or step through the trajectory.</p>"))
        items.append(molecule(data["symbols"], data.get("frames", [data["positions"]])))
        encoded = base64.b64encode(data["xyz"].encode()).decode()
        items.append(ipw.HTML(f'<a download="geometry.xyz" href="data:text/plain;base64,{encoded}"><i class="fa fa-download" aria-hidden="true"></i> Download final XYZ</a>'))
        provenance += f'<p>Structure: <code>{data["structure_uuid"]}</code></p>'
    if data["optimized"] and "summary" in data:
        energies = data["summary"]["scf_evaluation_energies_hartree"]
        fig, ax = plt.subplots(figsize=(7.4, 2.7))
        ax.plot(range(1, len(energies)+1), [(e-energies[-1])*27.211386245988 for e in energies], "o-", color="#237b98")
        ax.set(xlabel="SCF evaluation (including final evaluation)", ylabel="E − final E (eV)")
        ax.grid(alpha=0.2)
        fig.tight_layout()
        stream = io.BytesIO()
        fig.savefig(stream, format="png", dpi=140)
        plt.close(fig)
        items.append(ipw.Image(value=stream.getvalue(), format="png"))
    items.append(ipw.HTML(f"<details><summary>Provenance and identifiers</summary>{provenance}</details>"))
    return ipw.VBox(items)
