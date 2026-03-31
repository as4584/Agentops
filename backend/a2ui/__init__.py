"""A2UI package — agent-to-UI protocol for server-driven canvas rendering."""

from backend.a2ui.bus import A2UIBus, get_a2ui_bus
from backend.a2ui.schema import A2UIAction, A2UIComponentType, A2UIMessage, A2UIOp

__all__ = ["A2UIMessage", "A2UIAction", "A2UIComponentType", "A2UIOp", "A2UIBus", "get_a2ui_bus"]
