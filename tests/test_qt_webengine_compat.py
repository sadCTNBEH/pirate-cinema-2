from enum import Enum, auto
import sys
from types import ModuleType, SimpleNamespace


def test_permission_callback_uses_qt_enum_values(monkeypatch):
    class Policy(Enum):
        PermissionGrantedByUser = auto()
        PermissionDeniedByUser = auto()

    class Feature(Enum):
        MediaAudioCapture = auto()
        MediaVideoCapture = auto()
        MediaAudioVideoCapture = auto()
        ClipboardReadWrite = auto()

    class WebPage:
        def setFeaturePermission(self, url, feature, policy):
            assert isinstance(policy, Policy)
            self.permission = (url, feature, policy)

    webengine_module = ModuleType("qtpy.QtWebEngineCore")
    webengine_module.QWebEnginePage = SimpleNamespace(PermissionPolicy=Policy, Feature=Feature)
    qt_module = SimpleNamespace(is_webengine=True, BrowserView=SimpleNamespace(WebPage=WebPage))
    webview_module = ModuleType("webview")
    webview_module.__path__ = []
    webview_platforms_module = ModuleType("webview.platforms")
    webview_platforms_module.__path__ = []
    webview_platforms_module.qt = qt_module
    qtpy_module = ModuleType("qtpy")
    qtpy_module.__path__ = []
    monkeypatch.setitem(sys.modules, "qtpy", qtpy_module)
    monkeypatch.setitem(sys.modules, "qtpy.QtWebEngineCore", webengine_module)
    monkeypatch.setitem(sys.modules, "webview", webview_module)
    monkeypatch.setitem(sys.modules, "webview.platforms", webview_platforms_module)

    from backend.infrastructure.qt_webengine_compat import install_qt_permission_enum_compat

    assert install_qt_permission_enum_compat()
    page = WebPage()
    page.onFeaturePermissionRequested("https://trusted.local", Feature.MediaAudioCapture)
    assert page.permission == (
        "https://trusted.local",
        Feature.MediaAudioCapture,
        Policy.PermissionGrantedByUser,
    )

    page.onFeaturePermissionRequested("https://trusted.local", Feature.ClipboardReadWrite)
    assert page.permission == ("https://trusted.local", Feature.ClipboardReadWrite, Policy.PermissionDeniedByUser)
