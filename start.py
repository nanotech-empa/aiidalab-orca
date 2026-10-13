"""AiiDAlab home-page launcher using its standard start-widget interface."""

import html

import ipywidgets as ipw


def get_start_widget(appbase, jupbase):
    app = html.escape(appbase, quote=True)
    files = html.escape(jupbase, quote=True)
    return ipw.HTML(f"""
    <div style="padding:12px 16px;max-width:900px">
      <div style="display:flex;align-items:center;gap:20px;margin-bottom:20px">
        <img src="{files}/files/apps/orca/logo.svg" alt="ORCA molecular geometry" width="110" height="84">
        <div><h3 style="margin:0 0 6px">Molecular geometry</h3>
          <p style="margin:0;color:#495b66">Prepare, optimize, and reuse molecules with AiiDA provenance.</p></div>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:16px">
        <a href="{app}/start.ipynb" target="_blank" rel="noopener" style="display:flex;align-items:center;gap:16px;padding:18px 24px;border:1px solid #d4e4eb;border-radius:8px;background:#f1f7fa;text-decoration:none;color:#225c76;min-width:240px">
          <i class="fa fa-cubes" aria-hidden="true" style="font-size:34px"></i>
          <span><strong style="font-size:17px">New calculation</strong><br>Import, edit, and optimize a molecule</span>
        </a>
        <a href="{app}/search.ipynb" target="_blank" rel="noopener" style="display:flex;align-items:center;gap:16px;padding:18px 24px;border:1px solid #d4e4eb;border-radius:8px;background:#f1f7fa;text-decoration:none;color:#225c76;min-width:240px">
          <i class="fa fa-search" aria-hidden="true" style="font-size:34px"></i>
          <span><strong style="font-size:17px">Search calculations</strong><br>Explore results and reuse structures</span>
        </a>
      </div>
      <p style="color:#647783;margin-top:16px;font-size:13px">Geometry app · local ORCA execution</p>
    </div>
    """)
