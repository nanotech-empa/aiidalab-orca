"""Molecular trajectory and convergence display from serialized results."""

import base64
import html
import io

import ipywidgets as ipw
import matplotlib.pyplot as plt
import nglview as nv
from ase import Atoms


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
    title = "Optimized geometry" if data["optimized"] else "Supplied geometry · no optimization performed"
    items = [ipw.HTML(f"<h3>{title}</h3>")]
    provenance = f"<p>{html.escape(data['source_description'])}</p>"
    for warning in data.get("warnings", []):
        items.append(ipw.HTML(f"<p style='color:#a02020'>{html.escape(warning)}</p>"))
    if data.get("source_uuid"):
        items.append(ipw.HTML("<p><b>Reused an available optimization.</b> No new ORCA calculation was needed.</p>"))
        provenance += f"<p>Source workflow: <code>{data['source_uuid']}</code></p>"
    if "summary" in data:
        summary = data["summary"]
        text = (f"{s['method']}/{s['basis']} · charge {s['charge']} · multiplicity {s['multiplicity']}"
                f" · converged · E = {summary['energy_hartree']:.9f} Hartree")
        if "spin_squared" in summary:
            text += f" · ⟨S²⟩ = {summary['spin_squared']:.5f}"
        items.append(ipw.HTML(f"<p><b>{html.escape(text)}</b></p>"))
    if "positions" in data:
        if len(data.get("frames", [])) > 1:
            items.append(ipw.HTML("<p>Showing the final geometry. Move the pointer over the molecule to play or step through the trajectory.</p>"))
        items.append(molecule(data["symbols"], data.get("frames", [data["positions"]])))
        encoded = base64.b64encode(data["xyz"].encode()).decode()
        items.append(ipw.HTML(f'<a download="geometry.xyz" href="data:text/plain;base64,{encoded}"><i class="fa fa-download" aria-hidden="true"></i> Download final XYZ</a>'))
        provenance += f'<p>Structure: <code>{data["structure_uuid"]}</code></p>'
    if "summary" in data:
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
