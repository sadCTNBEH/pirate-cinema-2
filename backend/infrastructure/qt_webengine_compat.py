"""Compatibility fixes for Qt WebEngine integration in pywebview."""


def install_qt_permission_enum_compat() -> bool:
    """Pass Qt permission policy enums to PyQt6 instead of pywebview's raw ints."""
    try:
        from qtpy.QtWebEngineCore import QWebEnginePage
        from webview.platforms import qt
    except (ImportError, OSError):
        return False

    if not getattr(qt, "is_webengine", False):
        return False

    page = qt.BrowserView.WebPage
    if getattr(page, "_pc_permission_enum_compat_installed", False):
        return True

    policy_type = getattr(QWebEnginePage, "PermissionPolicy", None)
    feature_type = getattr(QWebEnginePage, "Feature", None)
    if policy_type is None or feature_type is None:
        return False

    granted = getattr(policy_type, "PermissionGrantedByUser", None)
    denied = getattr(policy_type, "PermissionDeniedByUser", None)
    media_features = {
        feature
        for feature in (
            getattr(feature_type, "MediaAudioCapture", None),
            getattr(feature_type, "MediaVideoCapture", None),
            getattr(feature_type, "MediaAudioVideoCapture", None),
        )
        if feature is not None
    }
    if granted is None or denied is None:
        return False

    def on_feature_permission_requested(self, url, feature):
        policy = granted if feature in media_features else denied
        self.setFeaturePermission(url, feature, policy)

    page.onFeaturePermissionRequested = on_feature_permission_requested
    page._pc_permission_enum_compat_installed = True
    return True
