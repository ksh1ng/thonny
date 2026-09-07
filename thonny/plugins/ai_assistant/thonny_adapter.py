"""Integration seams audited against Thonny 1a919b8f (6.0.0.dev1).

Callbacks are delivered on Thonny's UI thread. ProgramOutput does not include
a reliable run ID: subscribers must not treat receipt as execution ownership.
"""


class ThonnyAdapter:
    EVENTS = (
        "ProgramOutput", "ToplevelResponse", "CommandAccepted",
        "BackendRestart", "BackendTerminated", "InputRequest",
    )

    def __init__(self, workbench, runner):
        self.workbench = workbench
        self.runner = runner
        self._bindings = []

    def subscribe(self, callback):
        if self._bindings:
            raise RuntimeError("Adapter is already subscribed")
        for name in self.EVENTS:
            def handler(event, event_name=name):
                callback(event_name, event)
            self.workbench.bind(name, handler, True)
            self._bindings.append((name, handler))

    def close(self):
        for name, handler in self._bindings:
            self.workbench.unbind(name, handler)
        self._bindings.clear()

    def write_editor(self, code):
        notebook = self.workbench.get_editor_notebook()
        editor = notebook.get_current_editor()
        if editor is None:
            notebook.open_new_file()
            editor = notebook.get_current_editor()
        view = editor.get_code_view()
        view.text.edit_separator()
        view.set_content(code, keep_undo=True)
        view.text.edit_separator()
        return editor

    def execute_current(self):
        if not self.runner.get_backend_proxy():
            raise RuntimeError("Connect a target interpreter first")
        if not self.runner.is_waiting_toplevel_command():
            raise RuntimeError("Stop the current program before running generated code")
        self.runner.execute_current("Run")

    def list_esp32_ports(self):
        from thonny.plugins.esp import ESP32Proxy
        from thonny.plugins.micropython.mp_front import list_serial_ports
        from thonny.plugins.ai_assistant.device_setup import port_choices

        ports = list_serial_ports(max_cache_age=0, skip_logging=True)
        potential = {device for device, _ in ESP32Proxy._detect_potential_ports()}
        return port_choices(ports, potential)

    def configure_esp32(self, port):
        if not port:
            raise ValueError("Select an ESP32 serial port")
        self.workbench.set_option("run.backend_name", "ESP32")
        self.workbench.set_option("ESP32.port", port)
        self.runner.restart_backend(clean=False, first=False, automatic=False)

    def open_esp32_firmware_installer(self):
        from thonny.plugins.micropython.esptool_dialog import try_launch_esptool_dialog

        return try_launch_esptool_dialog(self.workbench, "MicroPython")

    def write_main_to_device(self, code):
        from thonny.common import InlineCommand

        if not self.runner.ready_for_remote_file_operations(show_message=True):
            raise RuntimeError("The MicroPython target is not ready for file operations")
        result = self.runner.send_command_and_wait(
            InlineCommand(
                "write_file", path="/main.py", content_bytes=code.encode("utf-8"),
                blocking=True, description="Saving /main.py", editor_id=id(self),
                make_shebang_scripts_executable=False,
            ),
            dialog_title="Saving to ESP32",
        )
        if result is None or "error" in result:
            raise RuntimeError((result or {}).get("error", "Could not save /main.py"))
        self.workbench.event_generate("RemoteFileOperation", path="/main.py", operation="save")
        return True
