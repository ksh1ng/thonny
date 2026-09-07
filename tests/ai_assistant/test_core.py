import io
import json
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

from thonny.plugins.ai_assistant.code_sanitizer import extract_code, redact
from thonny.plugins.ai_assistant.config_manager import ConfigManager
from thonny.plugins.ai_assistant.device_setup import SetupState, choose_state, port_choices, requests_esp32
from thonny.plugins.ai_assistant.hardware_context import detect_hardware, describe_hardware
from thonny.plugins.ai_assistant.models import GenerationRequest
from thonny.plugins.ai_assistant.providers.openai_compatible import OpenAICompatibleProvider, endpoint, profile_for


class Response(io.BytesIO):
    def __init__(self, data, content_type="application/json"):
        super().__init__(data)
        self.headers = {"content-type": content_type, "x-request-id": "request-1"}
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class ConfigTests(unittest.TestCase):
    def test_secret_is_session_or_environment_only(self):
        wb = Mock()
        config = ConfigManager(wb, {"OPENAI_API_KEY": "environment-secret"})
        self.assertEqual(config.get_api_key("openai"), "environment-secret")
        config.set_session_key("openai", "session-secret")
        self.assertEqual(config.get_api_key("openai"), "session-secret")
        with self.assertRaises(ValueError): config.set("api_key", "must-not-persist")
        self.assertNotIn("must-not-persist", repr(wb.mock_calls))


class ProviderTests(unittest.TestCase):
    def test_profiles_and_url_normalization(self):
        self.assertEqual(endpoint("https://host/v1/", "/models"), "https://host/v1/models")
        for provider_id in ("nvidia", "gemini", "openai", "custom"):
            self.assertTrue(profile_for(provider_id).default_model)

    def test_models_response(self):
        opener = Mock(return_value=Response(json.dumps({"data": [{"id": "b"}, {"id": "a"}]}).encode()))
        client = OpenAICompatibleProvider("https://host/v1", "secret", opener)
        self.assertEqual(client.list_models(), ["a", "b"])
        request = opener.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer secret")

    def test_non_streaming_response(self):
        payload = {"choices": [{"message": {"content": "hello"}}]}
        client = OpenAICompatibleProvider("https://host/v1", opener=Mock(return_value=Response(json.dumps(payload).encode())))
        deltas = []
        result = client.generate(GenerationRequest("model", [{"role": "user", "content": "hi"}]), deltas.append, Event())
        self.assertEqual(result.text, "hello")
        self.assertEqual(deltas, ["hello"])

    def test_streaming_response(self):
        data = b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\ndata: {"choices":[{"delta":{"content":"lo"}}]}\n\ndata: [DONE]\n'
        client = OpenAICompatibleProvider("https://host/v1", opener=Mock(return_value=Response(data, "text/event-stream")))
        deltas = []
        result = client.generate(GenerationRequest("model", []), deltas.append, Event())
        self.assertEqual(result.text, "hello")
        self.assertEqual(deltas, ["hel", "lo"])


class SanitizerTests(unittest.TestCase):
    def test_response_corpus(self):
        samples = ["```python\nprint(%d)\n```" % i for i in range(20)]
        for i, sample in enumerate(samples):
            self.assertEqual(extract_code(sample).code, "print(%d)\n" % i)

    def test_rejects_invalid_or_ambiguous(self):
        with self.assertRaises(ValueError): extract_code("not Python prose !")
        with self.assertRaises(ValueError): extract_code("```python\nprint(1)\n```\n```python\nprint(2)\n```")

    def test_warnings_and_redaction(self):
        self.assertIn("Desktop-only API", extract_code("import subprocess\n").warnings[0])
        output = redact("api_key=secret-value token: nvapi-abcdefghijkl")
        self.assertNotIn("secret-value", output)
        self.assertNotIn("nvapi-abcdefghijkl", output)


class HardwareTests(unittest.TestCase):
    def test_unknown_and_esp32(self):
        runner = Mock(); runner.get_backend_proxy.return_value = None
        unknown = detect_hardware(Mock(), runner)
        self.assertFalse(unknown.connected)
        self.assertIn("confirm", describe_hardware(unknown))
        runner.get_backend_proxy.return_value = object()
        wb = Mock(); wb.get_option.return_value = "ESP32MicroPython"
        context = detect_hardware(wb, runner)
        self.assertEqual(context.platform, "ESP32")
        self.assertNotIn("GPIO2", describe_hardware(context))


class DeviceSetupTests(unittest.TestCase):
    def test_detects_esp32_intent(self):
        self.assertTrue(requests_esp32("用 ESP32 做 LED blink"))
        self.assertTrue(requests_esp32("configure my esp-32 board"))
        self.assertFalse(requests_esp32("write a Python loop"))

    def test_setup_state(self):
        self.assertEqual(choose_state([], "Local Python 3", False), SetupState.CONNECT_DEVICE)
        self.assertEqual(choose_state([object()], "Local Python 3", False), SetupState.SELECT_PORT)
        self.assertEqual(choose_state([], "ESP32", True), SetupState.READY)

    def test_prioritizes_thonny_detected_ports(self):
        ports = [
            SimpleNamespace(device="/dev/a", description="USB serial"),
            SimpleNamespace(device="/dev/b", description="ESP32"),
        ]
        choices = port_choices(ports, {"/dev/b"})
        self.assertFalse(choices[0].likely_esp32)
        self.assertTrue(choices[1].likely_esp32)
