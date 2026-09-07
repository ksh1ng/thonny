import ast
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SanitizedCode:
    code: str
    warnings: tuple[str, ...]


def extract_code(text):
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.I | re.S)
    candidates = blocks or [text]
    valid = []
    for candidate in candidates:
        code = candidate.strip() + "\n"
        try:
            ast.parse(code)
        except SyntaxError:
            continue
        valid.append(code)
    if not valid:
        raise ValueError("The response does not contain valid Python code")
    if len(set(valid)) > 1:
        raise ValueError("The response contains multiple valid code blocks")
    code = valid[0]
    warnings = []
    for forbidden in ("subprocess", "socketserver", "os.path", "sys.argv"):
        if forbidden in code:
            warnings.append("Desktop-only API: " + forbidden)
    return SanitizedCode(code, tuple(warnings))


def redact(text):
    patterns = (
        r"(?i)(api[_ -]?key|token|password)\s*[:=]\s*(['\"]?)[^\s,'\"]+",
        r"\b(?:sk|nvapi)-[A-Za-z0-9_-]{8,}\b",
    )
    for pattern in patterns:
        text = re.sub(pattern, lambda m: m.group(0).split(":")[0].split("=")[0] + "=[REDACTED]", text)
    return text
