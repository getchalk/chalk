"""
src/companion - Ultra-lightweight Whiteboard Camera Companion System for Chalk.
Zero cloud, zero external CDN, zero friction.
"""

from .qr_generator import QRCode
from .bridge import CompanionBridge
from .server import CompanionServer

__all__ = ["QRCode", "CompanionBridge", "CompanionServer"]
