"""AiiDAlab home-page launcher using its standard start-widget interface."""

import html

import ipywidgets as ipw


def get_start_widget(appbase, jupbase):
    app = html.escape(appbase, quote=True)
    files = html.escape(jupbase, quote=True)
    return ipw.HTML(f"""
    <div style="padding:12px 16px;max-width:900px">
      <div style="display:flex;align-items:center;gap:20px;margin-bottom:20px">
        <img src="{files}/files/apps/orca/logo.svg" alt="ORCA molecular analysis" width="110" height="84">
        <div><h3 style="margin:0 0 6px">ORCA · Molecular analysis</h3>
          <p style="margin:0;color:#495b66">Geometry, orbitals, electronic states and spectroscopy with AiiDA provenance.</p></div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:16px">
        <a href="{app}/orca.ipynb" target="_blank" rel="noopener" style="display:flex;align-items:center;gap:16px;padding:18px 24px;border:1px solid #d4e4eb;border-radius:8px;background:#f1f7fa;text-decoration:none;color:#225c76;min-width:240px">
          <i class="fa fa-flask" aria-hidden="true" style="font-size:34px"></i>
          <span><strong style="font-size:17px">Open molecular analysis</strong><br>Start a calculation or explore saved results</span>
        </a>
      </div>
    </div>
    """)
