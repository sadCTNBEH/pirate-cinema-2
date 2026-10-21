"""Online providers package."""

from backend.services.online.providers.base import OnlineProvider, StreamInfo
from backend.services.online.providers.generic import GenericHLSProvider
from backend.services.online.providers.rutube import RutubeProvider

__all__ = ["GenericHLSProvider", "OnlineProvider", "RutubeProvider", "StreamInfo"]
