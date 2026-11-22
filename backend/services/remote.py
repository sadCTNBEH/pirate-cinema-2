"""Service for LAN Web Remote control and QR code generation."""

import io
import logging
import socket
from pathlib import Path
from typing import Any

import qrcode
import qrcode.image.svg

from backend.core.settings import config

logger = logging.getLogger(__name__)

# Safe remote player commands allowed from mobile clients
ALLOWED_REMOTE_PLAYER_COMMANDS = frozenset({
    "cycle",
    "seek",
    "set_property",
    "set",
    "continuation",
    "osd-menu",
    "osd-input",
    "playlist-next",
    "playlist-prev",
    "stop",
    "pause",
    "play",
    "frame-step",
    "frame-back-step",
})

# Safe player properties allowed to be inspected or adjusted
ALLOWED_REMOTE_PROPERTIES = frozenset({
    "volume",
    "aid",
    "sid",
    "pause",
    "mute",
    "speed",
    "sub-delay",
    "audio-delay",
    "sub-pos",
    "sub-font-size",
    "sub-scale",
    "sub-visibility",
    "fullscreen",
    "time-pos",
    "chapter",
})

# Dangerous MPV commands that can execute arbitrary OS commands or spawn processes
FORBIDDEN_COMMAND_NAMES = frozenset({
    "run",
    "subprocess",
    "loadscript",
    "script-binding",
    "script-message",
    "script-message-to",
    "hook-add",
    "hook-ack",
    "write-watch-later-config",
})


def validate_remote_command(command: Any) -> bool:
    """
    Validate that player command from remote client is safe.
    Rejects arbitrary system calls, subprocess execution, or unsafe commands.
    Raises ValueError with descriptive message if command is disallowed.
    """
    if not isinstance(command, (list, tuple)) or not command:
        raise ValueError("Команда должна быть непустым списком")

    action = str(command[0]).strip().lower()

    if action in FORBIDDEN_COMMAND_NAMES:
        raise ValueError(f"Команда '{action}' запрещена: недопустимый системный вызов")

    if action not in ALLOWED_REMOTE_PLAYER_COMMANDS:
        raise ValueError(f"Неизвестная или запрещённая команда: '{action}'")

    if action in ("set_property", "set") and len(command) >= 2:
        prop_name = str(command[1]).strip().lower()
        if prop_name not in ALLOWED_REMOTE_PROPERTIES:
            raise ValueError(f"Изменение свойства '{prop_name}' запрещено с удалённого пульта")

    return True


def is_safe_remote_command(command: Any) -> bool:
    """Check if command is safe without raising exception."""
    try:
        return validate_remote_command(command)
    except ValueError:
        return False


def validate_media_path(path: str | Path) -> bool:
    """
    Validate that media path or source is safe:
    - Allows URLs (HTTP/HTTPS streaming e.g. TorrServer or catalog)
    - Allows magnet URIs (magnet:?xt=urn:btih:...)
    - For local paths, checks that path is within allowed data directories and has video extension.
    - Prevents directory traversal ('..') and access to system files outside media directories.
    """
    if not path or not isinstance(path, (str, Path)):
        raise ValueError("Некорректный путь к медиафайлу")

    path_str = str(path).strip()

    # Magnet links
    if path_str.startswith("magnet:?xt=urn:btih:"):
        return True

    # Streaming HTTP/HTTPS URLs (e.g. TorrServer stream, online catalog)
    if path_str.startswith(("http://", "https://")):
        return True

    # Reject URLs with other schemes (file://, smb://, etc.)
    if "://" in path_str:
        raise ValueError("Недопустимая схема URL для медиафайла")

    # Check for path traversal attempts
    normalized = Path(path_str)
    if ".." in normalized.parts:
        raise ValueError("Попытка выхода за пределы каталога (path traversal)")

    # Extension check
    suffix = normalized.suffix.lower()
    if suffix not in config.VIDEO_EXTENSIONS:
        raise ValueError(f"Неподдерживаемое или небезопасное расширение файла: {suffix}")

    # Check that file path resides inside allowed directories (data dir or app base dir)
    from backend.core.settings import BASE_DIR, get_data_dir
    allowed_dirs = [get_data_dir().resolve(), BASE_DIR.resolve()]

    try:
        resolved = normalized.resolve()
        is_inside = any(
            str(resolved).startswith(str(d)) or str(resolved) == str(d)
            for d in allowed_dirs
        )
        if not is_inside and normalized.is_absolute():
            raise ValueError(f"Доступ к файлу вне медиатеки запрещён: {normalized.name}")
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Некорректный путь к файлу: {e}") from e

    return True


def is_safe_media_source(source: str | Path) -> bool:
    """Check if media source is safe without raising exception."""
    try:
        return validate_media_path(source)
    except ValueError:
        return False


def generate_remote_session(host: str, ttl: float = 43200) -> str:
    """Generate a limited-lifetime session token for a remote LAN device."""
    from backend.services.mobile import mobile_access
    return mobile_access.generate_token(host, ttl=ttl)


def validate_remote_session(token: str, host: str) -> bool:
    """Validate a remote session token for the given client host."""
    from backend.services.mobile import mobile_access
    return mobile_access.validate_token(token, host)


def is_remote_session_expired(token: str) -> bool:
    """Check if remote session token has expired."""
    from backend.services.mobile import mobile_access
    return mobile_access.is_token_expired(token)


def revoke_remote_session(token: str) -> bool:
    """Revoke a remote session token."""
    from backend.services.mobile import mobile_access
    return mobile_access.revoke_token(token)


def get_lan_ip() -> str:
    """Retrieve the primary local LAN IP address of the machine."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for item in addr_info:
            ip = item[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    return "127.0.0.1"


def get_local_hostname() -> str:
    """Retrieve the mDNS hostname of the local machine ending in .local."""
    try:
        raw_name = socket.gethostname().strip().lower()
        raw_name = raw_name.removesuffix(".local")
        import re

        clean_name = re.sub(r"[^a-z0-9\-]", "-", raw_name).strip("-")
        if clean_name:
            return f"{clean_name}.local"
    except OSError as error:
        logger.debug("Could not determine local hostname: %s", error)
    return ""


def get_remote_url(port: int | None = None, prefer_local: bool = True) -> str:
    """Construct the full HTTP URL for the mobile web remote."""
    target_port = port or config.APP_PORT
    from backend.services.mobile import mobile_access
    pair_suffix = f"?pair={mobile_access.code}#pair={mobile_access.code}"
    if prefer_local:
        local_host = get_local_hostname()
        if local_host:
            return f"http://{local_host}:{target_port}/remote{pair_suffix}"
    ip = get_lan_ip()
    return f"http://{ip}:{target_port}/remote{pair_suffix}"


def generate_qr_svg(url: str) -> str:
    """Generate an inline SVG representation of a QR code pointing to the given URL."""
    import re

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    stream = io.BytesIO()
    img.save(stream)
    raw_svg = stream.getvalue().decode("utf-8")

    # Strip XML declaration if present
    if "<?xml" in raw_svg:
        raw_svg = raw_svg[raw_svg.find("<svg"):]

    # Ensure SVG scales cleanly inside its container and has solid black fill
    raw_svg = re.sub(r'width="[^"]+"', 'width="100%"', raw_svg, count=1)
    raw_svg = re.sub(r'height="[^"]+"', 'height="100%"', raw_svg, count=1)
    if '<path ' in raw_svg and 'fill=' not in raw_svg:
        raw_svg = raw_svg.replace('<path ', '<path fill="#000000" ', 1)
    return raw_svg


def get_remote_info(port: int | None = None) -> dict[str, Any]:
    """Return dictionary with remote URL, LAN IP, port, and QR code SVG."""
    target_port = port or config.APP_PORT
    local_host = get_local_hostname()
    ip = get_lan_ip()

    from backend.services.mobile import mobile_access
    pair_suffix = f"?pair={mobile_access.code}#pair={mobile_access.code}"

    local_url = (
        f"http://{local_host}:{target_port}/remote{pair_suffix}"
        if local_host
        else f"http://{ip}:{target_port}/remote{pair_suffix}"
    )
    ip_url = f"http://{ip}:{target_port}/remote{pair_suffix}"

    # Default to .local URL (permanent and resilient to DHCP changes)
    primary_url = local_url
    svg = generate_qr_svg(primary_url)
    ip_svg = generate_qr_svg(ip_url)

    return {
        "url": primary_url,
        "local_url": local_url,
        "ip_url": ip_url,
        "hostname": local_host,
        "ip": ip,
        "port": target_port,
        "code": mobile_access.code,
        "qr_svg": svg,
        "ip_qr_svg": ip_svg,
    }
