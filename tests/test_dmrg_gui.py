"""Real widgets/builders, synthetic provenance and intercepted dispatch; no native jobs."""

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from aiida import engine, orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca.dmrg import DmrgCalculation, hamiltonian_parameters
from aiidalab_orca import dmrg_services as service
from aiidalab_orca.dmrg import NativeDmrg
from aiidalab_orca.widget_lifecycle import close_widget_tree
from test_energy_retention import descriptor_source


@pytest.fixture
def context(aiida_profile_clean, aiida_localhost):
    uid = service.store_example()
    code = orm.InstalledCode(
        computer=aiida_localhost,
        label="released-block2",
        filepath_executable="/reviewed/block2main",
        default_calc_job_plugin="empa_orca.dmrg",
    ).store()
    code.base.extras.set("block2", {"version": "0.5.4", "artifact_sha256": "a" * 64})
    settings = {
        "nroots": 1,
        "max_bond_dimension": 32,
        "threads": 1,
        "memory_gb": 2,
        "max_sweeps": 32,
        "ordering": "none",
        "sweep_tolerance": 1e-9,
        "davidson_tolerance": 1e-10,
    }
    return uid, str(code.uuid), settings


def attach(node, name, output):
    output.base.links.add_incoming(node, link_type=LinkType.CREATE, link_label=name)
    return output.store()


def completed(context, aiida_localhost, status=0, final=-2.0):
    uid, code_uid, settings = context
    node = orm.CalcJobNode(computer=aiida_localhost, process_type=service.PROCESS)
    for name, value in [
        ("code", orm.load_code(code_uid)),
        ("hamiltonian", orm.load_node(uid)),
        ("settings", orm.Dict(dict=settings).store()),
    ]:
        node.base.links.add_incoming(
            value, link_type=LinkType.INPUT_CALC, link_label=name
        )
    source_node, native, _ = service._source(uid)
    if native is not None:
        node.base.links.add_incoming(
            native, link_type=LinkType.INPUT_CALC, link_label="native_export"
        )
    node.store()
    record = {
        "hamiltonian_sha256": service.source(uid)["sha256"],
        "energies_hartree": [final],
        "excitation_energies_ev": [0.0],
        "density_checks": [{"trace": 2.0, "natural_occupations": [2.0, 0.0, 0.0]}],
        "sweep_converged": status == 0,
        "bond_dimension_convergence_established": False,
        "checkpoint_storage": "remote",
        "sweeps_completed": 32,
        "two_site_to_one_site_at_sweep": 24,
    }
    attach(node, "results", orm.Dict(dict=record))
    attach(
        node,
        "remote_folder",
        orm.RemoteData(computer=aiida_localhost, remote_path="/preserved/dmrg"),
    )
    saved = orm.FolderData()
    saved.base.repository.put_object_from_filelike(
        io.BytesIO(b"checkpoint"), "mps/mps_info.bin"
    )
    stream = io.BytesIO()
    np.save(stream, np.full((32, 1), final))
    saved.base.repository.put_object_from_filelike(
        io.BytesIO(stream.getvalue()), "sweep_energies.npy"
    )
    attach(node, "retrieved", saved)
    node.set_process_state(engine.ProcessState.FINISHED)
    node.set_exit_status(status)
    return str(node.uuid)


def test_analytic_fixture_is_explicit_small_singlet_not_allyl(context):
    uid, _, _ = context
    item = service.source(uid)
    assert item["parameters"] == {"NORB": 3, "NELEC": 2, "MS2": 0}
    text = orm.load_node(uid).get_content()
    one_body = [
        float(line.split()[0]) for line in text.splitlines() if len(line.split()) == 5
    ][:3]
    singlets = sorted(one_body[i] + one_body[j] for i in range(3) for j in range(i, 3))
    assert singlets[:3] == pytest.approx([-2.0, -1.2, -0.4])


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"&FCI NORB=3,NELEC=2,MS2=0,&END\n",
        b"&FCI NORB=3,NELEC=3,MS2=1,&END\n1.0 1 1 0 0",
        b"x" * (service.UPLOAD_LIMIT + 1),
    ],
)
def test_empty_unsupported_or_oversized_upload_rejected(content, aiida_profile):
    with pytest.raises(ValueError):
        service.store_upload(content, "unsupported.fcidump")


@pytest.mark.parametrize("threads", [1, 4])
def test_real_builder_and_native_input_match_reviewed_thread_budget(
    context, threads, aiida_manager
):
    uid, code, settings = context
    settings = settings | {"threads": threads, "nroots": 3}
    plan = service.prepare(uid, code, settings, 600)
    builder = service.builder(plan)
    options = builder.metadata.options
    assert options.resources == {
        "num_machines": 1,
        "num_mpiprocs_per_machine": 1,
        "num_cores_per_mpiproc": threads,
    }
    assert options.withmpi is False and options.max_wallclock_seconds == 600
    process = instantiate_process(
        aiida_manager.get_runner(), DmrgCalculation, **builder._inputs()
    )
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        text = Path(folder.abspath, "dmrg.conf").read_text()
        assert text == plan["input"]
        assert f"num_thrds {threads}\n" in text and "nroots 3\n" in text
        assert info.local_copy_list == [
            (uid, "hamiltonian.fcidump", "hamiltonian.fcidump")
        ]
        assert not any("mps/" in value[0] for value in info.retrieve_list)


def test_code_identity_change_invalidates_dispatch(context):
    uid, code, settings = context
    plan = service.prepare(uid, code, settings)
    orm.load_code(code).base.extras.set(
        "block2", {"version": "0.5.4", "artifact_sha256": "b" * 64}
    )
    with pytest.raises(ValueError, match="changed"):
        service.builder(plan)


def test_external_export_is_reused_without_integral_repository_copy(
    context, aiida_localhost, tmp_path, aiida_manager
):
    uid, code, settings = context
    raw = orm.load_node(uid).get_content().encode()
    native = {
        "active_space": {"electrons": 2, "orbitals": [0, 1, 2]},
        "multiplicity": 1,
        "hamiltonian_sha256": hashlib.sha256(raw).hexdigest(),
    }
    outputs = descriptor_source(aiida_localhost, tmp_path, raw, native)
    plan = service.prepare(outputs["hamiltonian"], code, settings)
    builder = service.builder(plan)
    assert str(builder.native_export.uuid) == outputs["native_export"]
    process = instantiate_process(
        aiida_manager.get_runner(), DmrgCalculation, **builder._inputs()
    )
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        assert not info.local_copy_list
        assert info.remote_copy_list == [
            (
                str(aiida_localhost.uuid),
                str(tmp_path / "native_output/hamiltonian.fcidump"),
                "hamiltonian.fcidump",
            )
        ]
        assert "hamiltonian.fcidump" not in folder.get_content_list()
        assert "sha256sum -c hamiltonian.sha256" in info.prepend_text
        assert (
            Path(folder.abspath, "hamiltonian.sha256").read_text()
            == native["hamiltonian_sha256"] + "  hamiltonian.fcidump\n"
        )
    with pytest.raises(ValueError, match="same native export"):
        hamiltonian_parameters(builder.hamiltonian, orm.Dict(dict=native))
    other = orm.Dict(dict=native | {"multiplicity": 2})
    # A separately fabricated manifest cannot change the native sector.
    with pytest.raises(ValueError, match="same native export"):
        hamiltonian_parameters(builder.hamiltonian, other)

    # Restart must retain both the integral and the MPS remote-copy entries.
    parent_uid = completed((outputs["hamiltonian"], code, settings), aiida_localhost)
    restart = service.prepare(
        outputs["hamiltonian"],
        code,
        settings,
        parent_uuid=parent_uid,
        continue_sweeps=True,
    )
    process = instantiate_process(
        aiida_manager.get_runner(),
        DmrgCalculation,
        **service.builder(restart)._inputs(),
    )
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        assert [item[2] for item in info.remote_copy_list] == [
            "hamiltonian.fcidump",
            "mps",
        ]
        assert (
            "hamiltonian.sha256" in info.prepend_text
            and "dmrg-verify.sh" in info.prepend_text
        )


def test_restart_same_m_and_increased_m_keep_original_nodes(
    context, aiida_localhost, aiida_manager
):
    parent_uid = completed(context, aiida_localhost, status=311)
    parent = orm.load_node(parent_uid)
    before = parent.base.attributes.all
    uid, code, settings = context
    plan = service.prepare(
        uid, code, settings, parent_uuid=parent_uid, continue_sweeps=True
    )
    assert "onedot\n" in plan["input"] and "fullrestart\n" in plan["input"]
    builder = service.builder(plan)
    process = instantiate_process(
        aiida_manager.get_runner(), DmrgCalculation, **builder._inputs()
    )
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        assert info.remote_copy_list == [
            (str(aiida_localhost.uuid), "/preserved/dmrg/mps", "mps")
        ]
        assert "sha256sum" in Path(folder.abspath, "dmrg-verify.sh").read_text()
    increased = service.prepare(
        uid, code, settings | {"max_bond_dimension": 64}, parent_uuid=parent_uid
    )
    assert "twodot_to_onedot" in increased["input"]
    with pytest.raises(ValueError, match="same bond dimension"):
        service.prepare(
            uid,
            code,
            settings | {"max_bond_dimension": 64},
            parent_uuid=parent_uid,
            continue_sweeps=True,
        )
    assert orm.load_node(parent_uid).base.attributes.all == before


def test_nonconverged_results_are_visible_with_separate_verdicts(
    context, aiida_localhost
):
    uid = completed(context, aiida_localhost, status=311)
    data = service.result(uid)
    assert data["exit_status"] == 311 and data["results"]["sweep_converged"] is False
    assert data["checkpoint_uuid"] and len(data["sweep_energies"]) == 32
    assert not data["results"]["bond_dimension_convergence_established"]
    json.dumps(data)
    widget = NativeDmrg()
    try:
        widget.result_uuid.value = uid
        widget._open_result()
        text = "".join(x.value for x in widget.results.children)
        assert "Energy (Ha)" in text and "Sweep converged:</b> False" in text
        assert "dmrg-sweeps.csv" in text and "dmrg-sweeps.svg" in text
        widget._checkpoint()
        assert widget.parent.value == uid and widget.source.value == context[0]
        assert widget.plan is None and widget.submit_button.disabled
    finally:
        close_widget_tree(widget)


def test_real_widget_review_invalidation_and_double_click_dispatch(
    context, monkeypatch
):
    uid, code, _ = context
    calls = []
    monkeypatch.setattr(
        service,
        "submit",
        lambda plan, label: calls.append(plan)
        or {"uuid": "submitted-uuid", "reused": False},
    )
    widget = NativeDmrg()
    try:
        assert calls == []
        widget.source.value = uid
        widget.code.value = code
        widget.review_button.click()
        assert (
            widget.plan is not None
            and not widget.submit_button.disabled
            and calls == []
        )
        widget.bond.value = 64
        assert widget.plan is None and widget.submit_button.disabled
        widget.review_button.click()
        widget.submit_button.click()
        widget.submit_button.click()
        assert len(calls) == 1 and widget.process_uuid == "submitted-uuid"
        widget.review_button.click()
        widget.source.value = "missing-source"
        assert widget.plan is None and widget.submit_button.disabled
        widget.review_button.click()
        assert "unavailable" in widget.status.value and widget.submit_button.disabled
    finally:
        close_widget_tree(widget)


def test_dispatch_reuses_identical_request_and_blocks_other_active_native(
    context, aiida_localhost, monkeypatch
):
    uid, code, settings = context
    calls = []

    def dispatch(build):
        calls.append(build)
        node = orm.CalcJobNode(
            computer=aiida_localhost, process_type=service.PROCESS
        ).store()
        node.set_process_state(engine.ProcessState.WAITING)
        return node

    monkeypatch.setattr(service.engine, "submit", dispatch)
    import aiida.engine.daemon.client

    monkeypatch.setattr(
        aiida.engine.daemon.client,
        "get_daemon_client",
        lambda: SimpleNamespace(is_daemon_running=True),
    )
    plan = service.prepare(uid, code, settings)
    first = service.submit(plan, "First native request")
    second = service.submit(json.loads(json.dumps(plan)), "Duplicate")
    assert len(calls) == 1 and second == {"uuid": first["uuid"], "reused": True}
    other = service.prepare(uid, code, settings | {"max_bond_dimension": 64})
    with pytest.raises(ValueError, match="Another native job"):
        service.submit(other, "Different request")
    assert len(calls) == 1


def test_no_native_code_is_an_explicit_prerequisite(aiida_profile, monkeypatch):
    monkeypatch.setattr(service, "codes", lambda: [])
    widget = NativeDmrg()
    try:
        assert (
            "No verified Block2" in widget.status.value
            and widget.submit_button.disabled
        )
        widget.review_button.click()
        assert "Configure and select" in widget.status.value and widget.plan is None
    finally:
        close_widget_tree(widget)


def test_energy_route_offers_dmrg_only_for_supported_even_electron_spaces():
    from aiidalab_orca.energy_view import EnergyRoutes

    calls = []
    for electrons, orbitals, expected in [(2, 3, True), (3, 3, False), (2, 2, False)]:
        widget = EnergyRoutes(
            "reference",
            {},
            {"electrons": electrons, "orbitals": list(range(orbitals))},
            lambda: None,
            lambda: None,
            open_dmrg=lambda: calls.append("dmrg"),
        )
        try:
            assert ("dmrg" in dict(widget.choice.options).values()) is expected
            if expected:
                widget.choice.value = "dmrg"
                assert "No circuits or QPU" in widget.explanation.value and not calls
                widget.continue_button.click()
        finally:
            close_widget_tree(widget)
    assert calls == ["dmrg"]


def test_main_app_dmrg_tab_is_lazy_and_does_not_replace_geometry_draft(
    context, monkeypatch
):
    from aiidalab_orca.app import OrcaApp

    calls = []
    monkeypatch.setattr(service, "submit", lambda *args: calls.append(args))
    app = OrcaApp()
    try:
        assert app.dmrg_panel is None and app.pages.get_title(3) == "Native DMRG"
        app.pages.selected_index = 3
        panel = app.dmrg_panel
        assert isinstance(panel, NativeDmrg) and calls == []
        panel.source.value = context[0]
        app.pages.selected_index = 0
        app.pages.selected_index = 3
        assert (
            app.dmrg_panel is panel and panel.source.value == context[0] and calls == []
        )
    finally:
        close_widget_tree(app.dmrg_panel)
        app.close()


def test_dmrg_guide_is_packaged_for_in_app_chat():
    from aiidalab_orca.energy_guidance import combined_workflow_guides

    guides = {row["id"]: row for row in combined_workflow_guides()}
    text = guides["orca.dmrg"]["text"]
    assert "Use this result as checkpoint" in text and "fixed spatial orbitals" in text
    assert "separate from" in text and "QPU sampling" in text
    assert "L20" in text and "A unit test" in text and "311" in text


def test_molecular_workspace_rejects_a_different_or_stale_export(context, monkeypatch):
    from aiidalab_orca import energy_services

    rows = []
    monkeypatch.setattr(energy_services, "models", lambda *args: list(rows))
    widget = NativeDmrg("confirmed-reference", {"electrons": 2, "orbitals": [0, 1, 2]})
    try:
        assert widget.source.disabled
        widget.source.value = context[0]
        widget.code.value = context[1]
        widget.review_button.click()
        assert "this confirmed reference" in widget.status.value and widget.plan is None
        rows.append(
            {
                "uuid": context[0],
                "label": "Matching completed export",
                "finished_ok": True,
            }
        )
        widget._refresh()
        widget.model.value = context[0]
        widget.review_button.click()
        assert widget.plan is not None and not widget.submit_button.disabled
        rows.clear()
        widget._refresh()
        assert widget.plan is None and widget.submit_button.disabled
        widget.review_button.click()
        assert "this confirmed reference" in widget.status.value and widget.plan is None
    finally:
        close_widget_tree(widget)
