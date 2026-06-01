from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppContext:
    main_window: Any
    ui: Any
    session: Any
    widgets: Any
    controllers: dict[str, Any] = field(default_factory=dict)


class BaseController:
    """Shared controller base with access to app context objects."""

    def __init__(self, context: AppContext):
        self.context = context
        self.main_window = context.main_window
        self.ui = context.ui
        self.session = context.session
        self.widgets = context.widgets

    def bind(self):
        """Bind Qt signals. Optional override in subclasses."""
        return None
