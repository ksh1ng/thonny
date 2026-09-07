"""Initial native view. Generation controls are added in the UI checklist item."""

from tkinter import ttk

from thonny import get_runner, get_workbench
from thonny.plugins.ai_assistant.thonny_adapter import ThonnyAdapter


class AIAssistantView(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="AI Assistant", padding=8).grid(sticky="w")
        ttk.Label(
            self, text="MicroPython natural-language assistant\nIntegration checkpoint: sidebar ready",
            padding=8, wraplength=260,
        ).grid(sticky="w")
        self.status = ttk.Label(self, text="Ready", padding=8)
        self.status.grid(sticky="w")
        self.adapter = ThonnyAdapter(get_workbench(), get_runner())
        self.adapter.subscribe(self._on_backend_event)

    def _on_backend_event(self, name, event):
        if name in ("BackendRestart", "BackendTerminated", "ToplevelResponse"):
            self.status.configure(text=name)

    def destroy(self):
        self.adapter.close()
        super().destroy()
