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
