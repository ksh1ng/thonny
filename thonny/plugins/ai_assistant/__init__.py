"""MicroPython AI assistant, loaded by Thonny's built-in plug-in loader."""


def load_plugin():
    from thonny import get_workbench
    from thonny.plugins.ai_assistant.config_manager import ConfigManager
    from thonny.plugins.ai_assistant.ui_view import AIAssistantView

    ConfigManager(get_workbench()).install_defaults()
    get_workbench().add_view(AIAssistantView, "AI Assistant", "ne")
