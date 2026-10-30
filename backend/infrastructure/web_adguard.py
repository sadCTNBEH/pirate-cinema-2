"""Official AdGuard MV3 in the existing Windows WebView2 profile."""
import hashlib
import json
import os
import threading
import zipfile
from pathlib import Path

VERSION = '5.5.3.3'
ARCHIVE_URL = f'https://github.com/AdguardTeam/AdguardBrowserExtension/releases/download/v{VERSION}/edge-mv3.zip'
ARCHIVE_SHA256 = '20d51050319578a425d3df3de8456635083d9cee98954031057abac2ec364dc0'
SOURCE_URL = f'https://github.com/AdguardTeam/AdguardBrowserExtension/tree/v{VERSION}'


def extension_safe_window_handler(original):
    """An extension URL belongs to this profile, never to the user's Edge."""
    def handle(owner, sender, args):
        from urllib.parse import urlsplit
        if urlsplit(str(args.get_Uri())).scheme == 'chrome-extension':
            args.set_Handled(True)
            return
        return original(owner, sender, args)
    handle._pc_extension_safe = True
    return handle


def eligible_player(player):
    value = str(player or '').casefold()
    return any(name in value for name in ('kodik', 'cvh', 'alloha')) or value == 'animego online'


def extension_files(root):
    """Install an unchanged, pinned official binary. Never modify installed files."""
    folder = Path(root) / 'adguard' / VERSION
    manifest = folder / 'manifest.json'
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('manifest_version') != 3 or data.get('version') != VERSION:
            raise RuntimeError('Несовместимый манифест AdGuard')
        return folder
    import io

    import requests
    response = requests.get(ARCHIVE_URL, timeout=(10, 90))
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError('Контрольная сумма официальной сборки AdGuard не совпала')
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for item in archive.infolist():
            if not (folder / item.filename).resolve().is_relative_to(folder.resolve()):
                raise RuntimeError('Недопустимый путь в архиве AdGuard')
        archive.extractall(folder)
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if data.get('manifest_version') != 3:
        raise RuntimeError('Требуется AdGuard Manifest V3')
    # License/source information is outside the installed extension directory.
    license_response = requests.get(f'https://raw.githubusercontent.com/AdguardTeam/AdguardBrowserExtension/v{VERSION}/LICENSE', timeout=20)
    license_response.raise_for_status()
    (folder.parent / 'AdGuard-LICENSE.txt').write_text(license_response.text, encoding='utf-8')
    (folder.parent / 'AdGuard-source.txt').write_text(SOURCE_URL + '\n', encoding='utf-8')
    return folder


class AdguardBridge:
    def __init__(self, root=None, load=None, save=None):
        from backend.core.settings import get_data_dir, load_settings, save_settings
        self.root = Path(root) if root else get_data_dir()
        self.load, self.save = load or load_settings, save or save_settings
        self.supported = False
        self.error = ''
        self.runtime = ''
        self.control = self.profile = self.extension = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._lease = None
        self._player = ''
        self._installed = self._active = False
        self.events_ready = False
        self.app_url = None

    def status(self):
        return {'supported': self.supported, 'initialized': self._ready.is_set(), 'installed': self._installed,
            'enabled': bool(self.load().get('web_player_adguard', False)), 'active': self._active,
            'version': VERSION, 'runtime': self.runtime, 'error': self.error}

    def _ui(self, operation, timeout=30):
        if not self._ready.wait(20) or self.control is None:
            raise RuntimeError('WebView2 ещё не готов к работе с расширениями')
        from System import Action
        from System.Threading.Tasks import Task
        done = threading.Event()
        result = {}
        def finish(task):
            try:
                task.GetAwaiter().GetResult()
                prop = task.GetType().GetProperty('Result')
                result['value'] = prop.GetValue(task) if prop else None
            except Exception as error:  # noqa: BLE001
                result['error'] = str(error)
            finally:
                done.set()
        def invoke():
            try:
                task = operation()
                task.ContinueWith(Action[Task](finish), self.scheduler)
            except Exception as error:  # noqa: BLE001
                result['error'] = str(error); done.set()
        self.control.BeginInvoke(Action(invoke))
        if not done.wait(timeout):
            raise RuntimeError('WebView2 не завершил операцию с AdGuard вовремя')
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result.get('value')

    def _apply(self, enabled):
        if self.extension is not None and self._active != bool(enabled):
            self._ui(lambda: self.extension.EnableAsync(bool(enabled)))
            # Read COM properties only on the UI thread, via the completed operation.
            self._active = bool(enabled)

    def set_enabled(self, enabled):
        with self._lock:
            try:
                if not self.supported:
                    raise RuntimeError('Требуется совместимый Windows WebView2 с поддержкой расширений')
                if enabled and self.extension is None:
                    folder = extension_files(self.root)
                    self.extension = self._ui(lambda: self.profile.AddBrowserExtensionAsync(str(folder)))
                    self._installed = True
                    self._active = True
                self._apply(bool(enabled) and (not self._lease or eligible_player(self._player)))
                self.save({'web_player_adguard': bool(enabled)})
                self.error = ''
            except Exception as error:  # noqa: BLE001
                self.error = str(error)
            return self.status()

    def scope(self, player, lease):
        with self._lock:
            self._lease, self._player = str(lease), str(player)
            desired = bool(self.load().get('web_player_adguard', False))
            if desired:
                state = self.set_enabled(True)
                if state['error']:
                    return state
            elif self.extension is not None:
                self._apply(False)
            return self.status()

    def release(self, lease):
        with self._lock:
            if self._lease == str(lease):
                self._lease, self._player = None, ''
                if self.extension is not None:
                    self._apply(bool(self.load().get('web_player_adguard', False)))
            return self.status()

    def attach(self, control, args):
        if not args.IsSuccess:
            self.error = str(args.InitializationException); self._ready.set(); return
        from System import Action
        from System.Threading.Tasks import Task, TaskScheduler
        self.control, self.profile = control, control.CoreWebView2.Profile
        if self.app_url:
            from backend.infrastructure.web_player_events import (
                shell_navigation_allowed,
            )
            def navigation_starting(sender, event):
                if not shell_navigation_allowed(self.app_url, str(event.Uri)):
                    event.Cancel = True
            control.CoreWebView2.NavigationStarting += navigation_starting
        self.scheduler = TaskScheduler.FromCurrentSynchronizationContext()
        from backend.infrastructure.web_player_events import ALLOHA_EVENTS_SCRIPT
        def events_installed(task):
            try:
                task.GetAwaiter().GetResult()
                self.events_ready = True
            except Exception:  # noqa: BLE001
                self.events_ready = False
        control.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(ALLOHA_EVENTS_SCRIPT).ContinueWith(Action[Task](events_installed), self.scheduler)
        self.runtime = str(control.CoreWebView2.Environment.BrowserVersionString)
        def loaded(task):
            try:
                items = task.GetType().GetProperty('Result').GetValue(task)
                self.extension = next((item for item in items if 'adguard' in str(item.Name).casefold()), None)
                self._installed = self.extension is not None
                if self.extension is not None:
                    self._active = bool(self.extension.IsEnabled)
                self.error = ''
            except Exception as error:  # noqa: BLE001
                self.error = str(error)
            finally:
                self._ready.set()
            # Run the blocking bridge from a background thread, never the STA loop.
            if self.extension is not None:
                threading.Thread(target=lambda: self.set_enabled(bool(self.load().get('web_player_adguard', False))), daemon=True).start()
        self.profile.GetBrowserExtensionsAsync().ContinueWith(Action[Task](loaded), self.scheduler)


def install_native_bridge(bridge):
    """Only replace pywebview's native WebView2 constructor; keep its desktop shell."""
    if os.name != 'nt':
        return False
    try:
        # This backend loads pythonnet and registers the bundled WebView2 DLLs.
        # Their Microsoft.Web namespaces do not exist until it has been imported.
        from webview.platforms import edgechromium

        from Microsoft.Web.WebView2.Core import (
            CoreWebView2Environment,
            CoreWebView2EnvironmentOptions,
        )
        from System import Action
        from System.Threading.Tasks import Task, TaskScheduler
        native_type = edgechromium.WebView2
        version = str(CoreWebView2Environment.GetAvailableBrowserVersionString(None))
        if int(version.split('.')[0]) < 121:
            raise RuntimeError('AdGuard MV3 требует Chromium/WebView2 версии 121 или новее')
        options = CoreWebView2EnvironmentOptions()
        options.AreBrowserExtensionsEnabled = True
        popup_handler = edgechromium.EdgeChrome.on_new_window_request
        if not getattr(popup_handler, '_pc_extension_safe', False):
            edgechromium.EdgeChrome.on_new_window_request = extension_safe_window_handler(popup_handler)
        class ExtensionWebView(native_type):
            def __init__(self):
                super().__init__()
                self._adguard_environment_task = None
                self.CoreWebView2InitializationCompleted += bridge.attach

            def EnsureCoreWebView2Async(self, environment=None):
                if environment is not None:
                    return native_type.EnsureCoreWebView2Async(self, environment)
                if self._adguard_environment_task is not None:
                    return self._adguard_environment_task
                props = self.CreationProperties
                opts = CoreWebView2EnvironmentOptions()
                opts.AreBrowserExtensionsEnabled = True
                opts.AdditionalBrowserArguments = props.AdditionalBrowserArguments
                scheduler = TaskScheduler.FromCurrentSynchronizationContext()
                def created(task):
                    try:
                        env = task.GetType().GetProperty('Result').GetValue(task)
                        native_type.EnsureCoreWebView2Async(self, env)
                    except Exception as error:  # noqa: BLE001
                        bridge.error = str(error); bridge._ready.set()
                self._adguard_environment_task = CoreWebView2Environment.CreateAsync(props.BrowserExecutableFolder, props.UserDataFolder, opts)
                self._adguard_environment_task.ContinueWith(Action[Task](created), scheduler)
                return self._adguard_environment_task
        edgechromium.WebView2 = ExtensionWebView
        bridge.supported, bridge.runtime = True, version
        return True
    except Exception as error:  # noqa: BLE001
        bridge.error = str(error)
        return False


bridge = AdguardBridge()
