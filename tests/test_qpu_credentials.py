"""Account persistence and secret-free notebook state; no provider calls."""

import json
from pathlib import Path
import stat

import pytest

from aiidalab_orca import qpu_credentials as credentials


@pytest.fixture
def account_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    return tmp_path


def test_native_accounts_are_private_and_replacement_is_explicit(account_home):
    pytest.importorskip('qiskit_ibm_runtime')
    # Synthetic test credentials, never a real user's key.
    first, second = 'test_key_' + 'a' * 30, 'test_key_' + 'b' * 30
    crn = 'crn:v1:bluemix:public:quantum-computing:us-east:a:test:instance::'
    credentials.save_account('open', first, crn)
    credentials.save_account('project', second, crn)
    accounts, selection = credentials.paths()
    assert stat.S_IMODE(accounts.stat().st_mode) == 0o600
    assert stat.S_IMODE(accounts.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(selection.stat().st_mode) == 0o600
    assert set(json.loads(accounts.read_text())) == {'open', 'project'}
    with pytest.raises(credentials.CredentialSetupError, match='replacement'):
        credentials.save_account('open', second, crn)
    assert json.loads(accounts.read_text())['open']['token'] == first
    credentials.save_account('open', second, crn, replace=True)
    assert json.loads(accounts.read_text())['open']['token'] == second
    state = credentials.account_status()
    assert state['selected'] == 'open'
    assert first not in json.dumps(state) and second not in json.dumps(state)


def test_unsafe_storage_is_refused(account_home):
    external = account_home / 'external'
    external.mkdir()
    (account_home / '.qiskit').symlink_to(external)
    with pytest.raises(credentials.CredentialSetupError):
        credentials._write(credentials.paths()[0], {'example': {}})
    assert not (external / 'qiskit-ibm.json').exists()


def test_credential_directory_cannot_be_inside_git(account_home):
    (account_home / '.git').mkdir()
    with pytest.raises(credentials.CredentialSetupError, match='outside Git'):
        credentials._write(credentials.paths()[1], {})


def test_account_symlink_and_public_permissions_are_refused(account_home):
    path = credentials.paths()[0]
    path.parent.mkdir()
    outside = account_home / 'outside.json'
    outside.write_text('{}')
    outside.chmod(0o600)
    path.symlink_to(outside)
    with pytest.raises(credentials.CredentialSetupError):
        credentials.account_status()
    path.unlink()
    path.write_text('{}')
    path.chmod(0o644)
    with pytest.raises(credentials.CredentialSetupError):
        credentials.account_status()


def test_secret_is_transient_and_provider_errors_are_redacted(account_home, monkeypatch):
    token = 'test_key_' + 'x' * 30
    seen = []

    def failed(*args, **kwargs):
        seen.append(args[1])
        raise RuntimeError('provider error with ' + args[1])

    monkeypatch.setattr(credentials, 'save_account', failed)
    form = credentials.CredentialForm()
    message = {'action': 'save', 'name': 'test', 'token': token, 'instance': 'crn:test'}
    try:
        form._receive(None, message, [])
        assert seen == [token] and 'token' not in message
        assert token not in repr(form) and token not in json.dumps(form.get_state())
        assert 'failed' in form.status
        source = Path(credentials.__file__).parent / 'static' / 'qpu_credentials.js'
        assert 'model.set(' not in source.read_text()
        assert 'key.value = ""' in source.read_text()
    finally:
        form.close()


def test_opening_panel_does_not_connect(account_home, monkeypatch):
    monkeypatch.setattr(credentials, 'check_connection', lambda: pytest.fail('Unexpected connection'))
    panel = credentials.credentials_panel()
    try:
        assert panel.selected_index is None
        assert panel.titles == ('QPU credentials',)
    finally:
        from aiidalab_orca.widget_lifecycle import close_widget_tree
        close_widget_tree(panel)
