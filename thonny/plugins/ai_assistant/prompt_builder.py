from thonny.plugins.ai_assistant.code_sanitizer import redact
from thonny.plugins.ai_assistant.hardware_context import describe_hardware


SYSTEM_PROMPT = """You are an embedded MicroPython assistant inside Thonny.
Answer in the user's language. Prefer machine, network, time and uasyncio APIs.
Do not use desktop-only APIs such as subprocess, socketserver, os.path or sys.argv.
When returning code, use one complete Python fenced block. Long-running loops must
handle KeyboardInterrupt and leave outputs in a safe state. Explain uncertain pin
assignments instead of guessing. For hardware programs, print [HIL:READY] with a
short description only after peripheral initialization succeeds. Print [HIL:PASS]
only when the program has actually measured a testable invariant; never claim a
physical LED, motor, buzzer or display worked without sensor feedback. Keep
explanations concise. Probe external I2C/SPI/UART devices before the main loop.
When a probe shows missing power, wiring or a peripheral, print
[HIL:HW_ACTION] followed by a concrete wiring instruction and stop cleanly so
the assistant can pause for the user. Interactive input() prompts are allowed;
continue validation after the user responds in Thonny's Shell."""


def build_messages(history, hardware):
    context = SYSTEM_PROMPT + "\n\nHardware context: " + describe_hardware(hardware)
    return [{"role": "system", "content": context}] + list(history)


def build_repair_messages(requirement, code, output, reason, hardware):
    context = SYSTEM_PROMPT + "\n\nHardware context: " + describe_hardware(hardware)
    request = """Repair this MicroPython program after a hardware-in-the-loop run.
Return one complete replacement Python fenced block. Make the smallest justified
change. Preserve [HIL:READY] / [HIL:PASS] semantics and do not invent hardware
observations.

Original requirement:
{requirement}

Failure reason:
{reason}

Bounded target output:
{output}

Failed code:
{code}
""".format(
        requirement=redact(requirement),
        reason=redact(reason),
        output=redact(output[-12000:]),
        code=redact(code),
    )
    return [{"role": "system", "content": context}, {"role": "user", "content": request}]
