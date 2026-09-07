from thonny.plugins.ai_assistant.models import HardwareContext


def detect_hardware(workbench, runner):
    proxy = runner.get_backend_proxy()
    if proxy is None:
        return HardwareContext()
    backend_name = str(workbench.get_option("run.backend_name", "unknown"))
    lower = backend_name.lower()
    if "esp32" in lower:
        platform = "ESP32"
    elif "esp8266" in lower:
        platform = "ESP8266"
    elif "pico" in lower or "rp2040" in lower:
        platform = "RP2040"
    elif "micro" in lower:
        platform = "MicroPython"
    else:
        platform = backend_name
    return HardwareContext(platform=platform, board=backend_name, connected=True)


def describe_hardware(context):
    if not context.connected:
        return "No target connected. Ask the user to confirm board and pin assignments."
    return (
        "Detected platform: %s; backend/board hint: %s. Do not assume an onboard LED pin "
        "unless the exact board is known; ask the user or expose a named constant."
    ) % (context.platform, context.board)
