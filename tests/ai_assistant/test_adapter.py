import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from thonny.plugins.ai_assistant.thonny_adapter import ThonnyAdapter


class AdapterTests(unittest.TestCase):
    def test_plugin_registers_native_view(self):
        from thonny.plugins.ai_assistant import load_plugin
        from thonny.plugins.ai_assistant.ui_view import AIAssistantView

        workbench = Mock()
        with patch("thonny.get_workbench", return_value=workbench):
            load_plugin()
        workbench.add_view.assert_called_once_with(AIAssistantView, "AI Assistant", "ne")

    def test_events_and_disposal(self):
        workbench = Mock()
        adapter = ThonnyAdapter(workbench, Mock())
        callback = Mock()
        adapter.subscribe(callback)
        event = SimpleNamespace(data="hello", stream_name="stdout")
        for call in workbench.bind.call_args_list:
            name, handler, add = call.args
            self.assertTrue(add)
            handler(event)
            callback.assert_called_with(name, event)
        adapter.close()
        self.assertEqual(workbench.unbind.call_count, len(adapter.EVENTS))
        adapter.close()
        self.assertEqual(workbench.unbind.call_count, len(adapter.EVENTS))

    def test_editor_retains_undo(self):
        workbench = Mock()
        view = workbench.get_editor_notebook().get_current_editor().get_code_view()
        ThonnyAdapter(workbench, Mock()).write_editor("print(1)\n")
        view.set_content.assert_called_once_with("print(1)\n", keep_undo=True)
        self.assertEqual(view.text.edit_separator.call_count, 2)

    def test_run_requires_idle_backend(self):
        runner = Mock()
        runner.get_backend_proxy.return_value = None
        adapter = ThonnyAdapter(Mock(), runner)
        with self.assertRaises(RuntimeError):
            adapter.execute_current()
        runner.get_backend_proxy.return_value = object()
        runner.is_waiting_toplevel_command.return_value = False
        with self.assertRaises(RuntimeError):
            adapter.execute_current()
        runner.execute_current.assert_not_called()
        runner.is_waiting_toplevel_command.return_value = True
        adapter.execute_current()
        runner.execute_current.assert_called_once_with("Run")

    def test_configure_esp32_updates_options_and_restarts(self):
        workbench, runner = Mock(), Mock()
        ThonnyAdapter(workbench, runner).configure_esp32("/dev/cu.usbserial-test")
        workbench.set_option.assert_any_call("run.backend_name", "ESP32")
        workbench.set_option.assert_any_call("ESP32.port", "/dev/cu.usbserial-test")
        runner.restart_backend.assert_called_once_with(clean=False, first=False, automatic=False)

    def test_interrupt_uses_connected_backend_proxy(self):
        runner = Mock()
        proxy = runner.get_backend_proxy.return_value
        proxy.is_connected.return_value = True
        adapter = ThonnyAdapter(Mock(), runner)
        self.assertTrue(adapter.ready_for_run())
        adapter.interrupt_current()
        proxy.interrupt.assert_called_once_with()
