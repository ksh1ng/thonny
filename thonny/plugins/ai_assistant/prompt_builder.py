from thonny.plugins.ai_assistant.hardware_context import describe_hardware


SYSTEM_PROMPT = """You are an embedded MicroPython assistant inside Thonny.
Answer in the user's language. Prefer machine, network, time and uasyncio APIs.
Do not use desktop-only APIs such as subprocess, socketserver, os.path or sys.argv.
When returning code, use one complete Python fenced block. Long-running loops must
handle KeyboardInterrupt and leave outputs in a safe state. Explain uncertain pin
assignments instead of guessing. Keep explanations concise."""


def build_messages(history, hardware):
    context = SYSTEM_PROMPT + "\n\nHardware context: " + describe_hardware(hardware)
    return [{"role": "system", "content": context}] + list(history)
