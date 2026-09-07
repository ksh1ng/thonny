"""MicroPython AI assistant, loaded by Thonny's built-in plug-in loader."""


def load_plugin():
    from thonny import get_workbench
    from thonny.plugins.ai_assistant.ui_view import AIAssistantView

    get_workbench().add_view(AIAssistantView, "AI Assistant", "ne")
