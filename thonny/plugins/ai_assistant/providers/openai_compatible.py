import json
import socket
import urllib.error
import urllib.request

from thonny.plugins.ai_assistant.models import GenerationResult, ProviderProfile
from thonny.plugins.ai_assistant.providers.base import (
    AuthenticationError, ProviderError, RateLimitError, RequestCancelled,
)


PROFILES = (
    ProviderProfile("codex", "OpenAI Account (Codex)", "", "gpt-5.6-sol"),
    ProviderProfile("nvidia", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "meta/llama-3.3-70b-instruct"),
    ProviderProfile("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    ProviderProfile("openai", "OpenAI API", "https://api.openai.com/v1", "gpt-4.1-mini"),
    ProviderProfile("custom", "Custom / Local", "http://localhost:11434/v1", "qwen2.5-coder"),
)


def profile_for(provider_id):
    return next(profile for profile in PROFILES if profile.id == provider_id)


def endpoint(base_url, path):
    return base_url.rstrip("/") + "/" + path.lstrip("/")


class OpenAICompatibleProvider:
    def __init__(self, base_url, api_key="", opener=None):
        self.base_url = base_url
        self.api_key = api_key
        self.opener = opener or urllib.request.urlopen

    def _request(self, path, data=None, timeout=30):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = urllib.request.Request(
            endpoint(self.base_url, path), data=data, headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            return self.opener(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthenticationError("API authentication failed") from exc
            if exc.code == 429:
                raise RateLimitError("API rate limit reached") from exc
            raise ProviderError("API returned HTTP %s" % exc.code) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ProviderError("Could not reach the model provider: %s" % exc) from exc

    def list_models(self, timeout=20):
        with self._request("models", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
        result = []
        for item in items:
            model_id = item.get("id", item.get("name")) if isinstance(item, dict) else item
            if model_id:
                result.append(str(model_id).removeprefix("models/"))
        return sorted(set(result))

    def generate(self, request, on_delta, cancel):
        body = json.dumps({"model": request.model, "messages": request.messages, "stream": True}).encode("utf-8")
        chunks = []
        request_id = None
        with self._request("chat/completions", body, request.timeout) as response:
            request_id = response.headers.get("x-request-id")
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type:
                payload = json.loads(response.read().decode("utf-8"))
                text = payload["choices"][0]["message"]["content"]
                on_delta(text)
                return GenerationResult(text, request.model, request_id)
            for raw_line in response:
                if cancel.is_set():
                    raise RequestCancelled("Request cancelled")
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                delta = event.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                if delta:
                    chunks.append(delta)
                    on_delta(delta)
        return GenerationResult("".join(chunks), request.model, request_id)
