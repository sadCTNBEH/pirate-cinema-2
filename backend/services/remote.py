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


def get_remote_url(port: int | None = None) -> str:
    """Construct the full HTTP URL for the mobile web remote."""
    ip = get_lan_ip()
    target_port = port or config.APP_PORT
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
    url = get_remote_url(port)
    svg = generate_qr_svg(url)
    return {
        "url": url,
        "ip": get_lan_ip(),
        "port": port or config.APP_PORT,
        "qr_svg": svg,
    }
