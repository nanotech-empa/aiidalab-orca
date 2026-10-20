# Assistant integration and compatibility

On 20 October 2026 Carlo authorized consolidating the Home and ORCA assistant
on the existing AiiDAlab 26.6.0 container. The 26.9 minimum originated in the
general support policy, not an identified API dependency. This branch lowers
only the AiiDAlab requirement to 26.6 and adds both 26.6 and 26.9 to the CI
matrix. This is a scoped compatibility exception, not a change to the wider
EMPA support policy. Local validation uses Python 3.12.11, AiiDA 2.9.2 and
ipywidgets 8.1.8. CI results for 26.9 remain a separate check.
Retire the exception after the instance is deliberately upgraded to the wider
baseline and the integrated applications are revalidated there.

The assistant changes are based on the completed open-shell/XPS work at
`69cb0f1d447f06d76359227806cbb5738728165f`. The scientific backend is identical
to that revision. No database migration, result conversion or recalculation is
required by this integration. Existing scientific limitations and protocol
compatibility checks still apply.

Installing the separate `aiidalab-ai-assistant` package adds an assistant panel
to the normal ORCA notebook. It shares conversations and provider/model/thinking
preferences with Home. The adapter can inspect a calculation, select its results,
load a stored structure, and update or undo geometry/SCF setup fields. Reviewed
submission and process controls use explicit confirmation in the panel.
Spectroscopy-specific settings, including XPS and cobalt multiplets, remain
available in the existing result/analysis GUI.

The shared package supplies openBIS inspection tools and a Git-maintained how-to.
Creation, import, export and upload use links to the existing openBIS GUI.
Automatic prefilling of those notebooks is not implemented.

The form adapter also reports the current page, review readiness and displayed
structure/settings/resource/error messages. Review and submission failures return
the actual displayed text. These display-only fields do not change the revision
used to protect the user's newer edits.

Install the assistant and this frontend/backend from their intended checkouts,
using `--no-deps` when retaining an already provisioned scientific environment,
and run `python -m pip check`. Reopen the application after switching checkouts;
already running notebook kernels retain their imported modules.
