import io
import unittest
from threading import Event
from unittest.mock import Mock

from thonny.plugins.ai_assistant.models import GenerationRequest
from thonny.plugins.ai_assistant.providers.codex_account import CodexAccountProvider


class CapturingInput(io.StringIO):
    def close(self): pass


class FakeProcess:
    def __init__(self):
        self.stdin = CapturingInput()
        self.stdout = io.StringIO('{"type":"item.completed","item":{"type":"agent_message","text":"answer"}}\n')
        self.stderr = io.StringIO()
        self.returncode = None
    def wait(self, timeout=None): self.returncode = 0; return 0
    def poll(self): return self.returncode
    def kill(self): self.returncode = -9
    def terminate(self): self.returncode = -15


class CodexAccountTests(unittest.TestCase):
    def test_status_and_machine_readable_generation(self):
        status = Mock(return_value=Mock(returncode=0, stdout="Logged in using ChatGPT", stderr=""))
        process = FakeProcess(); popen = Mock(return_value=process)
        provider = CodexAccountProvider("/bin/codex", popen=popen, run=status)
        deltas = []
        result = provider.generate(GenerationRequest("model-a", [{"role": "user", "content": "hello"}]), deltas.append, Event())
        self.assertEqual(result.text, "answer")
        self.assertEqual(deltas, ["answer"])
        args = popen.call_args.args[0]
        self.assertIn("--json", args); self.assertIn("--ephemeral", args)
        self.assertIn("read-only", args); self.assertNotIn("danger-full-access", args)
        self.assertIn("hello", process.stdin.getvalue())

    def test_login_and_logout_are_delegated(self):
        run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        popen = Mock()
        provider = CodexAccountProvider("/bin/codex", popen=popen, run=run)
        provider.login(); provider.logout()
        popen.assert_called_once_with(["/bin/codex", "login"])
        self.assertIn("logout", run.call_args.args[0])
