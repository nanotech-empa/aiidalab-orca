"""Local IBM account setup. Secrets never become widget traits or AiiDA data."""

import json
import os
from pathlib import Path
import re
import stat
import tempfile

import anywidget
import ipywidgets as ipw
import traitlets as tl


class CredentialSetupError(ValueError):
    """A public message that contains no credential or provider exception."""


def paths():
    return (Path.home() / '.qiskit' / 'qiskit-ibm.json',
            Path.home() / '.config' / 'aiidalab-orca' / 'qpu.json')


def _directory(path):
    for parent in (path, *path.parents):
        if parent.is_symlink() or (parent / '.git').exists():
            raise CredentialSetupError('Credential storage must be outside Git and symbolic links.')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise CredentialSetupError('Credential directory must belong to this user.')
    path.chmod(0o700)


def _read(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    except OSError:
        raise CredentialSetupError('Account configuration cannot be opened safely.') from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1024 * 1024):
            raise CredentialSetupError('Account files must be regular owner-only files (600).')
        with os.fdopen(fd, encoding='utf-8') as stream:
            fd = None
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise CredentialSetupError('Account configuration cannot be read safely.') from None
    finally:
        if fd is not None:
            os.close(fd)


def _write(path, data):
    _directory(path.parent)
    _read(path)  # Refuse symlinks or unsafe existing files before replacement.
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def account_status():
    accounts_path, selection_path = paths()
    accounts = _read(accounts_path)
    selected = _read(selection_path).get('ibm_account', '')
    return {'accounts': [{'name': name, 'instance': value.get('instance', '')}
                         for name, value in accounts.items()
                         if isinstance(value, dict) and value.get('channel') == 'ibm_quantum_platform'],
            'selected': selected}


def select_account(name):
    if name not in {row['name'] for row in account_status()['accounts']}:
        raise CredentialSetupError('Choose a saved IBM Quantum account.')
    _write(paths()[1], {'ibm_account': name})


def save_account(name, token, instance, *, replace=False):
    if not isinstance(name, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) is None:
        raise CredentialSetupError('Use 1–64 letters, numbers, underscores or hyphens for the account name.')
    if not isinstance(token, str) or re.fullmatch(r'[A-Za-z0-9_-]{20,256}', token.strip()) is None:
        raise CredentialSetupError('Enter a valid IBM Cloud API key.')
    if not isinstance(instance, str) or not instance.startswith('crn:') or len(instance) > 512:
        raise CredentialSetupError('Enter the explicit instance CRN supplied by IBM or your project.')
    path, _ = paths()
    accounts = _read(path)
    if name in accounts and not replace:
        raise CredentialSetupError('This account exists. Enable replacement explicitly to update it.')
    _directory(path.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    os.close(fd)
    try:
        Path(temporary).write_text(json.dumps(accounts))
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService
            QiskitRuntimeService.save_account(
                token=token.strip(), instance=instance.strip(), channel='ibm_quantum_platform',
                name=name, filename=temporary, overwrite=replace, set_as_default=False)
        except ImportError:
            raise CredentialSetupError('Install the IBM Runtime worker tools through your AiiDAlab setup.') from None
        except Exception:
            raise CredentialSetupError('IBM account validation failed; no account was changed.') from None
        _write(path, json.loads(Path(temporary).read_text()))
    finally:
        Path(temporary).unlink(missing_ok=True)
    select_account(name)


def check_connection():
    """Read-only provider connection; no backend execution or sampling."""
    state = account_status()
    if not state['selected']:
        raise CredentialSetupError('Select a saved account first.')
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
        service = QiskitRuntimeService(name=state['selected'], filename=str(paths()[0]))
        expected = next(row['instance'] for row in state['accounts'] if row['name'] == state['selected'])
        if service.active_instance() != expected:
            raise ValueError()
    except Exception:
        raise CredentialSetupError('Connection was not verified. Check the key, instance access and network.') from None


class CredentialForm(anywidget.AnyWidget):
    """The secret exists only in a DOM input and a transient comm message."""

    _esm = Path(__file__).parent / 'static' / 'qpu_credentials.js'
    accounts = tl.List(tl.Dict()).tag(sync=True)
    selected = tl.Unicode().tag(sync=True)
    status = tl.Unicode().tag(sync=True)

    def __init__(self):
        super().__init__()
        self.on_msg(self._receive)
        self._refresh()

    def _refresh(self):
        try:
            state = account_status()
            self.accounts, self.selected = state['accounts'], state['selected']
            self.status = ('Selected local account: ' + self.selected if self.selected
                           else 'No account selected. Saving does not contact IBM or submit a job.')
        except Exception:
            self.status = 'Local account configuration is unavailable or has unsafe permissions.'

    def _receive(self, _, content, buffers):
        token = content.pop('token', '')
        try:
            action = content.get('action')
            if action == 'save':
                save_account(content.get('name'), token, content.get('instance'),
                             replace=content.get('replace') is True)
            elif action == 'select':
                select_account(content.get('name'))
            elif action == 'check':
                check_connection()
            elif action != 'refresh':
                return
            self._refresh()
            if action == 'check':
                self.status = 'Connection verified for the selected instance. No QPU job submitted.'
        except CredentialSetupError as error:
            self.status = str(error)
        except Exception:
            self.status = 'Credential setup failed. No diagnostic containing the key is displayed.'
        finally:
            token = ''


def credentials_panel():
    form = CredentialForm()
    box = ipw.Accordion(children=[ipw.VBox([
        ipw.HTML('<p>Configure IBM Quantum on <b>this AiiDAlab server</b>. A remote worker needs its own '
                 'account setup; keys are never copied through AiiDA. Credentials are saved locally with '
                 'owner-only permissions. Enter keys only here, never in chat or notebook cells. '
                 'Use the project’s assigned instance CRN when access is granted. '
                 'Existing Open-plan research pilots retain their separate account configuration.</p>'), form])],
        titles=['QPU credentials'], selected_index=None)
    return box
