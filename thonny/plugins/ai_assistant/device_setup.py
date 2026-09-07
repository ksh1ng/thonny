from dataclasses import dataclass
from enum import Enum


class SetupState(Enum):
    IDLE = "idle"
    CONNECT_DEVICE = "connect_device"
    SELECT_PORT = "select_port"
    CONNECTING = "connecting"
    READY = "ready"
    FIRMWARE_REQUIRED = "firmware_required"


@dataclass(frozen=True)
class PortChoice:
    device: str
    label: str
    likely_esp32: bool


ESP32_TERMS = ("esp32", "esp-32")


def requests_esp32(text):
    lower = text.lower()
    return any(term in lower for term in ESP32_TERMS)


def choose_state(ports, backend_name, connected):
    if backend_name == "ESP32" and connected:
        return SetupState.READY
    if not ports:
        return SetupState.CONNECT_DEVICE
    if backend_name == "ESP32":
        return SetupState.CONNECTING
    return SetupState.SELECT_PORT


def port_choices(serial_ports, potential_devices):
    potential_devices = set(potential_devices)
    return [
        PortChoice(
            port.device,
            "%s — %s" % (port.device, port.description or "Serial device"),
            port.device in potential_devices,
        )
        for port in serial_ports
    ]
