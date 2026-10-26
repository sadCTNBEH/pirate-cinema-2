import json
import logging
from pathlib import Path
from typing import Any

from backend.core.settings.base import BASE_DIR, get_data_dir
from backend.core.settings.config import config
from backend.models.search import TorznabConfig

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "hotkeys": {},
    "language": "ru",
    "torrserver_url": config.TORRSERVER_DEFAULT_URL,
    "torrserver_endpoint": config.TORRSERVER_DEFAULT_URL,
    "jackett_url": "",
    "jackett_api_key": "",
    "jackett_key": "",
    "torznab_url": "",
    "torznab_api_key": "",
    "torznab_enabled": False,
    "torznab_categories": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
    "torznab": {
        "enabled": False,
        "url": "",
        "api_key": "",
        "categories": [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060],
    },
    "player_type": "mpv",  # "mpv" | "external"
    "player_path": "",
    "embedded_player": True,
    "onboarding_complete": False,
    "minimize_to_tray": True,
    "close_behavior_configured": False,
    "register_magnet_handler": False,
    "autostart": False,
    "autostart_prompted": False,
}


def settings_path() -> Path:
    return get_data_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        merged = DEFAULT_SETTINGS.copy()
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})

        # Sync TorrServer aliases
        ts_url = (
            data.get("torrserver_url")
            or data.get("torrserver_endpoint")
            or config.TORRSERVER_DEFAULT_URL
        )
        merged["torrserver_url"] = ts_url
        merged["torrserver_endpoint"] = ts_url

        # Sync Jackett / Torznab aliases
        tz_raw = merged.get("torznab")
        tz_dict = tz_raw.copy() if isinstance(tz_raw, dict) else {}

        t_url = (
            tz_dict.get("url")
            or merged.get("torznab_url")
            or merged.get("jackett_url")
            or ""
        )
        t_key = (
            tz_dict.get("api_key")
            or merged.get("torznab_api_key")
            or merged.get("jackett_api_key")
            or merged.get("jackett_key")
            or ""
        )
        t_cats = (
            tz_dict.get("categories")
            or merged.get("torznab_categories")
            or [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]
        )
        t_enabled = tz_dict.get("enabled", merged.get("torznab_enabled", bool(t_url)))

        merged["jackett_url"] = t_url
        merged["jackett_api_key"] = t_key
        merged["jackett_key"] = t_key
        merged["torznab_url"] = t_url
        merged["torznab_api_key"] = t_key
        merged["torznab_enabled"] = t_enabled
        merged["torznab_categories"] = t_cats
        merged["torznab"] = {
            "enabled": t_enabled,
            "url": t_url,
            "api_key": t_key,
            "categories": t_cats,
        }

        return merged
    except (OSError, json.JSONDecodeError):
        logger.exception("Error loading settings")
        return DEFAULT_SETTINGS.copy()


def save_settings(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_settings()
    current.update(data)

    # Sync torznab and jackett fields before saving
    if "torznab" in data and isinstance(data["torznab"], dict):
        tz = data["torznab"]
        if "url" in tz:
            current["jackett_url"] = tz["url"]
            current["torznab_url"] = tz["url"]
        if "api_key" in tz:
            current["jackett_api_key"] = tz["api_key"]
            current["torznab_api_key"] = tz["api_key"]
        if "enabled" in tz:
            current["torznab_enabled"] = tz["enabled"]
        if "categories" in tz:
            current["torznab_categories"] = tz["categories"]
    elif "jackett_url" in data or "jackett_api_key" in data:
        j_url = current.get("jackett_url", "")
        j_key = current.get("jackett_api_key", "")
        current["torznab_url"] = j_url
        current["torznab_api_key"] = j_key
        current["torznab"] = {
            "enabled": current.get("torznab_enabled", bool(j_url)),
            "url": j_url,
            "api_key": j_key,
            "categories": current.get(
                "torznab_categories", [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]
            ),
        }

    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def get_torrserver_url() -> str:
    return load_settings().get("torrserver_endpoint", config.TORRSERVER_DEFAULT_URL)


def get_torznab_config() -> TorznabConfig:
    s = load_settings()
    tz = s.get("torznab") or {}
    enabled = tz.get("enabled", s.get("torznab_enabled", False))
    url = tz.get("url") or s.get("torznab_url") or s.get("jackett_url") or ""
    api_key = (
        tz.get("api_key") or s.get("torznab_api_key") or s.get("jackett_api_key") or ""
    )
    categories = tz.get("categories") or s.get("torznab_categories") or []
    return TorznabConfig(
        enabled=enabled,
        url=url,
        api_key=api_key,
        categories=categories,
    )


def _find_mpv_in_registry() -> Path | None:
    import sys
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    # 1. Check App Paths in HKCU and HKLM
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in (
            r"Software\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe",
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe",
            r"Software\Microsoft\Windows\CurrentVersion\App Paths\mpvnet.exe",
        ):
            try:
                with winreg.OpenKey(root, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val:
                        p = Path(str(val).strip('"').strip())
                        if p.is_file():
                            return p
            except OSError:
                pass

    # 2. Check shell open command / file association
    for subkey in (
        r"Applications\mpv.exe\shell\open\command",
        r"Applications\mpvnet.exe\shell\open\command",
        r"io.mpv\shell\open\command",
        r"mpv\shell\open\command",
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val:
                    val_str = str(val).strip()
                    import shlex
                    try:
                        parts = shlex.split(val_str)
                        if parts:
                            p = Path(parts[0])
                            if p.is_file():
                                return p
                    except ValueError as e:
                        logger.debug("Invalid MPV shell command in registry: %s", e)
                    if ".exe" in val_str.lower():
                        idx = val_str.lower().find(".exe") + 4
                        candidate = val_str[:idx].strip('"').strip()
                        p = Path(candidate)
                        if p.is_file():
                            return p
        except OSError:
            pass

    # 3. Check Uninstall keys
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in (
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(root, subkey) as ukey:
                    num_subkeys = winreg.QueryInfoKey(ukey)[0]
                    for i in range(num_subkeys):
                        try:
                            sub_name = winreg.EnumKey(ukey, i)
                            if "mpv" in sub_name.lower():
                                with winreg.OpenKey(ukey, sub_name) as app_key:
                                    for prop in ("InstallLocation", "DisplayIcon"):
                                        try:
                                            v, _ = winreg.QueryValueEx(app_key, prop)
                                            if v:
                                                p = Path(str(v).strip('"').strip())
                                                if p.is_file() and p.name.lower().endswith(".exe"):
                                                    return p
                                                if (p / "mpv.exe").is_file():
                                                    return p / "mpv.exe"
                                        except OSError:
                                            pass
                        except OSError:
                            pass
            except OSError:
                pass

    return None


def find_mpv_binary(prefs: dict[str, Any] | None = None) -> Path | None:
    """Find mpv binary across user settings, bundled assets, portable paths, system registry, and PATH."""
    import os
    import shutil
    import sys

    if prefs is None:
        prefs = load_settings()

    def usable(path: Path) -> bool:
        return path.is_file() and (
            sys.platform == "win32" or (path.suffix.lower() != ".exe" and os.access(path, os.X_OK))
        )

    # 1. User custom setting
    if prefs.get("player_path"):
        custom = Path(str(prefs["player_path"]).strip('"').strip()).expanduser()
        if usable(custom):
            return custom
        if custom.is_dir():
            for name in ("mpv.exe", "mpv", "mpvnet.exe"):
                candidate = custom / name
                if usable(candidate):
                    return candidate

    binary_name = "mpv.exe" if sys.platform == "win32" else "mpv"

    # 2. Bundled and local application directories
    candidates: list[Path] = [
        BASE_DIR / "vendor" / "mpv" / binary_name,
        BASE_DIR / "_internal" / "vendor" / "mpv" / binary_name,
        BASE_DIR / "mpv" / binary_name,
        BASE_DIR / binary_name,
    ]

    exe_parent = Path(sys.executable).parent
    candidates.extend([
        exe_parent / "_internal" / "vendor" / "mpv" / binary_name,
        exe_parent / "vendor" / "mpv" / binary_name,
        exe_parent / "mpv" / binary_name,
        exe_parent / binary_name,
    ])

    data_dir = get_data_dir()
    candidates.extend([
        data_dir / "vendor" / "mpv" / binary_name,
        data_dir / "mpv" / binary_name,
    ])

    try:
        cwd = Path.cwd()
        candidates.extend([
            cwd / "vendor" / "mpv" / binary_name,
            cwd / "_internal" / "vendor" / "mpv" / binary_name,
            cwd / "mpv" / binary_name,
            cwd / binary_name,
        ])
    except OSError:
        pass

    # 3. Windows-specific registry & directory search
    if sys.platform == "win32":
        reg_mpv = _find_mpv_in_registry()
        if reg_mpv and reg_mpv.is_file():
            return reg_mpv

        for pf_env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            pf_dir = os.environ.get(pf_env)
            if pf_dir:
                p_base = Path(pf_dir)
                candidates.extend([
                    p_base / "mpv" / "mpv.exe",
                    p_base / "MPV Player" / "mpv.exe",
                    p_base / "mpv.net" / "mpvnet.exe",
                    p_base / "mpv.net_portable" / "mpvnet.exe",
                    p_base / "mpv" / "mpv.com",
                ])

        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            l_base = Path(local_app)
            candidates.extend([
                l_base / "Programs" / "mpv" / "mpv.exe",
                l_base / "Programs" / "Pirate Cinema" / "_internal" / "vendor" / "mpv" / "mpv.exe",
                l_base / "Programs" / "Pirate Cinema" / "vendor" / "mpv" / "mpv.exe",
                l_base / "Programs" / "mpv.net" / "mpvnet.exe",
                l_base / "mpv" / "mpv.exe",
                l_base / "Microsoft" / "WinGet" / "Links" / "mpv.exe",
            ])

        roaming_app = os.environ.get("APPDATA")
        if roaming_app:
            r_base = Path(roaming_app)
            candidates.extend([
                r_base / "mpv" / "mpv.exe",
                r_base / "mpv.net" / "mpvnet.exe",
            ])

        home = Path.home()
        candidates.extend([
            Path("C:/mpv/mpv.exe"),
            Path("C:/tools/mpv/mpv.exe"),
            Path("D:/mpv/mpv.exe"),
            home / "mpv" / "mpv.exe",
            home / "Downloads" / "mpv" / "mpv.exe",
            home / "Desktop" / "mpv" / "mpv.exe",
            home / "scoop" / "apps" / "mpv" / "current" / "mpv.exe",
            home / "scoop" / "shims" / "mpv.exe",
            Path(os.environ.get("ProgramData", "C:/ProgramData")) / "chocolatey" / "bin" / "mpv.exe",
        ])

    else:
        candidates.extend([
            Path("/usr/bin/mpv"),
            Path("/usr/local/bin/mpv"),
            Path("/opt/homebrew/bin/mpv"),
            Path.home() / ".local" / "bin" / "mpv",
            Path("/snap/bin/mpv"),
            Path("/var/lib/flatpak/exports/bin/io.mpv.Mpv"),
        ])

    for c in candidates:
        try:
            if c and usable(c):
                # Snap dispatches by argv[0]; resolving /snap/bin/mpv to /usr/bin/snap breaks it.
                return c.resolve() if sys.platform == "win32" else c.absolute()
        except OSError:
            pass

    # 4. PATH search
    which_mpv = shutil.which(binary_name) or shutil.which("mpv")
    if which_mpv:
        p_which = Path(which_mpv)
        if usable(p_which):
            return p_which.resolve() if sys.platform == "win32" else p_which.absolute()

    if sys.platform == "win32":
        which_mpvnet = shutil.which("mpvnet.exe") or shutil.which("mpvnet")
        if which_mpvnet:
            p_net = Path(which_mpvnet)
            if p_net.is_file():
                return p_net.resolve()

    return None


def resolve_mpv_binary(prefs: dict[str, Any] | None = None) -> Path:
    import sys
    found = find_mpv_binary(prefs)
    if found is not None:
        return found
    return Path("mpv.exe" if sys.platform == "win32" else "mpv")
