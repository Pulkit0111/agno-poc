"""The manager: an Agno Team leader carrying Bott's personality that chats directly and
delegates real work to specialist members.
"""
from .manager import build_manager, get_manager, run_manager
from .personality import IDENTITY, NAME, VOICE

__all__ = ["build_manager", "get_manager", "run_manager", "NAME", "IDENTITY", "VOICE"]
