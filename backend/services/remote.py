"""Service for LAN Web Remote control and QR code generation."""

import io
import logging
import socket
from typing import Any

import qrcode
import qrcode.image.svg

from backend.core.settings import config

logger = logging.getLogger(__name__)


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
        if raw_name.endswith(".local"):
            raw_name = raw_name[:-6]
        import re

        clean_name = re.sub(r"[^a-z0-9\-]", "-", raw_name).strip("-")
        if clean_name:
            return f"{clean_name}.local"
    except Exception:
        pass
    return ""


def get_remote_url(port: int | None = None, prefer_local: bool = True) -> str:
    """Construct the full HTTP URL for the mobile web remote."""
    target_port = port or config.APP_PORT
    if prefer_local:
        local_host = get_local_hostname()
        if local_host:
            return f"http://{local_host}:{target_port}/remote"
    ip = get_lan_ip()
    return f"http://{ip}:{target_port}/remote"


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

    local_url = (
        f"http://{local_host}:{target_port}/remote"
        if local_host
        else f"http://{ip}:{target_port}/remote"
    )
    ip_url = f"http://{ip}:{target_port}/remote"

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
        "qr_svg": svg,
        "ip_qr_svg": ip_svg,
    }
