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
    slider = ipw.IntSlider(description="Geometry", min=0, max=len(frames)-1,
                           value=len(frames)-1, continuous_update=False)
    link = ipw.jslink((slider, "value"), (view, "frame"))
    view.frame = slider.value
    return MolecularView([view, slider], link)


class MolecularView(ipw.VBox):
    def __init__(self, children, link):
        self._frame_link = link
        super().__init__(children)

    def close(self):
        if getattr(self, "_frame_link", None):
            self._frame_link.unlink()
            self._frame_link = None
        super().close()


def show_result(data):
    s = data["settings"]
    title = "Optimized geometry" if data["optimized"] else "Supplied geometry · no optimization performed"
    items = [ipw.HTML(f"<h3>{title}</h3><p>{html.escape(data['source_description'])}</p>")]
    for warning in data.get("warnings", []):
        items.append(ipw.HTML(f"<p style='color:#a02020'>{html.escape(warning)}</p>"))
    if data.get("source_uuid"):
        items.append(ipw.HTML(f"<p>Reused stored result: <code>{data['source_uuid']}</code></p>"))
    if "summary" in data:
        summary = data["summary"]
        text = (f"{s['method']}/{s['basis']} · charge {s['charge']} · multiplicity {s['multiplicity']}"
                f" · converged · E = {summary['energy_hartree']:.9f} Hartree")
        if "spin_squared" in summary:
            text += f" · ⟨S²⟩ = {summary['spin_squared']:.5f}"
        items.append(ipw.HTML(f"<p><b>{html.escape(text)}</b></p>"))
    if "positions" in data:
        items.append(molecule(data["symbols"], data.get("frames", [data["positions"]])))
        encoded = base64.b64encode(data["xyz"].encode()).decode()
        items.append(ipw.HTML(f'<a download="geometry.xyz" href="data:text/plain;base64,{encoded}">Download final XYZ</a>'
                             f'<details><summary>Structure identifier</summary><code>{data["structure_uuid"]}</code></details>'))
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
    return ipw.VBox(items)
