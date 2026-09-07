import json
import os
import shutil
import subprocess

from thonny.plugins.ai_assistant.models import GenerationResult
from thonny.plugins.ai_assistant.providers.base import AuthenticationError, ProviderError, RequestCancelled


DEFAULT_CODEX_PATHS = (
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "/Applications/Codex.app/Contents/Resources/codex",
)


def find_codex(environ=None):
    environ = os.environ if environ is None else environ
    configured = environ.get("THONNY_CODEX_PATH")
    candidates = (configured, shutil.which("codex"), *DEFAULT_CODEX_PATHS)
    return next((path for path in candidates if path and os.path.isfile(path) and os.access(path, os.X_OK)), None)


class CodexAccountProvider:
    """Delegates account auth and model access to the official Codex client."""

    def __init__(self, executable=None, popen=subprocess.Popen, run=subprocess.run):
        self.executable = executable or find_codex()
        if not self.executable:
            raise ProviderError("Codex CLI not found. Install Codex or set THONNY_CODEX_PATH.")
        self.popen, self.run = popen, run

    def auth_status(self):
        result = self.run([self.executable, "login", "status"], capture_output=True, text=True, timeout=15)
        text = (result.stdout + result.stderr).strip()
        return result.returncode == 0, text

    def login(self):
        return self.popen([self.executable, "login"])

    def logout(self):
        return self.run([self.executable, "logout"], capture_output=True, text=True, timeout=30)

    def list_models(self, timeout=20):
        # The CLI has no stable model-list command. Selection remains editable and
        # Codex validates account/workspace availability when generation starts.
        return ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"]

    def generate(self, request, on_delta, cancel):
        logged_in, detail = self.auth_status()
        if not logged_in:
            raise AuthenticationError(detail or "Sign in with your OpenAI account first")
        prompt = "\n\n".join("%s:\n%s" % (m["role"], m["content"]) for m in request.messages)
        args = [self.executable, "exec", "--json", "--ephemeral", "--ignore-rules", "--skip-git-repo-check", "--sandbox", "read-only", "--model", request.model, "-"]
        process = self.popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        process.stdin.write(prompt); process.stdin.close()
        chunks = []
        try:
            for line in process.stdout:
                if cancel.is_set():
                    process.terminate()
                    raise RequestCancelled("Request cancelled")
                try: event = json.loads(line)
                except json.JSONDecodeError: continue
                item = event.get("item", {})
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    text = item.get("text", "")
                    if text: chunks.append(text); on_delta(text)
            returncode = process.wait(timeout=request.timeout)
            if returncode:
                error = process.stderr.read().strip()
                raise ProviderError(error[-500:] or "Codex generation failed")
        finally:
            if process.poll() is None: process.kill()
        return GenerationResult("".join(chunks), request.model)
