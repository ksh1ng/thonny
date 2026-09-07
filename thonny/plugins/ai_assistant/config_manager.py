import os


PREFIX = "ai_assistant."

DEFAULTS = {
    "provider": "nvidia",
    "model": "meta/llama-3.3-70b-instruct",
    "custom_url": "http://localhost:11434/v1",
    "write_editor": True,
    "auto_run": False,
    "auto_fix": True,
}


class ConfigManager:
    """Persists non-secret preferences; API keys stay in memory or environment."""

    def __init__(self, workbench, environ=None):
        self.workbench = workbench
        self.environ = os.environ if environ is None else environ
        self._session_keys = {}

    def install_defaults(self):
        for name, value in DEFAULTS.items():
            self.workbench.set_default(PREFIX + name, value)

    def get(self, name):
        return self.workbench.get_option(PREFIX + name, DEFAULTS.get(name))

    def set(self, name, value):
        if name == "api_key":
            raise ValueError("Secrets may not be stored in Thonny options")
        self.workbench.set_option(PREFIX + name, value)

    def set_session_key(self, provider_id, value):
        if value:
            self._session_keys[provider_id] = value
        else:
            self._session_keys.pop(provider_id, None)

    def get_api_key(self, provider_id):
        env_names = {
            "nvidia": "NVIDIA_API_KEY", "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY", "custom": "CUSTOM_LLM_API_KEY",
        }
        if provider_id == "codex":
            return ""
        return self._session_keys.get(provider_id) or self.environ.get(env_names[provider_id], "")

    @staticmethod
    def masked(value):
        return "" if not value else ("••••" + value[-4:] if len(value) > 4 else "••••")
