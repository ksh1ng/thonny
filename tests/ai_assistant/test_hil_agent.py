import unittest

from thonny.plugins.ai_assistant.hil_agent import HilAgent, HilState


class HilAgentTests(unittest.TestCase):
    def test_ready_requires_physical_confirmation(self):
        agent = HilAgent()
        agent.start("blink LED", "print('[HIL:READY]')")
        agent.command_accepted("Run")
        decision = agent.feed_output("[HIL:READY] LED loop started\n")
        self.assertEqual(decision.state, HilState.AWAITING_OBSERVATION)
        self.assertEqual(agent.observe(True).state, HilState.PASSED)

    def test_measured_pass_can_finish_automatically(self):
        agent = HilAgent()
        agent.start("read sensor", "print('[HIL:PASS]')")
        agent.command_accepted("Run")
        decision = agent.feed_output("sample=42\n[HIL:PASS] range check\n")
        self.assertEqual(decision.state, HilState.PASSED)

    def test_traceback_requests_bounded_repairs(self):
        agent = HilAgent(max_repairs=2)
        agent.start("blink", "bad0", attempt=0)
        agent.command_accepted("Run")
        first = agent.feed_output("Traceback (most recent call last):\nValueError: pin")
        self.assertTrue(first.request_repair)
        agent.start("blink", "bad1", attempt=1)
        agent.command_accepted("Run")
        second = agent.feed_output("\nOSError: device")
        self.assertTrue(second.request_repair)
        agent.start("blink", "bad2", attempt=2)
        agent.command_accepted("Run")
        third = agent.feed_output("Traceback (most recent call last):\nMemoryError:")
        self.assertFalse(third.request_repair)

    def test_unchanged_repair_is_not_executed(self):
        agent = HilAgent()
        agent.start("blink", "same", attempt=0)
        decision = agent.start("blink", "same", attempt=1)
        self.assertEqual(decision.state, HilState.FAILED)
        self.assertFalse(decision.request_repair)

    def test_input_and_disconnect_do_not_repair(self):
        agent = HilAgent()
        agent.start("wifi", "input()")
        agent.command_accepted("Run")
        self.assertEqual(agent.input_requested().state, HilState.WAITING_INPUT)
        self.assertFalse(agent.input_requested().request_repair)
        self.assertEqual(agent.disconnected().state, HilState.DISCONNECTED)

    def test_output_is_bounded(self):
        agent = HilAgent(max_output_chars=20)
        agent.start("task", "code")
        agent.command_accepted("Run")
        agent.feed_output("x" * 100)
        self.assertEqual(len(agent.active.output), 20)

    def test_timeout_is_correlated_to_active_run(self):
        agent = HilAgent()
        agent.start("blink", "code")
        run_id = agent.active.run_id
        agent.command_accepted("Run")
        self.assertIsNone(agent.observation_timeout("stale-run"))
        self.assertEqual(
            agent.observation_timeout(run_id).state, HilState.AWAITING_OBSERVATION
        )

    def test_stale_output_is_ignored_until_run_is_accepted(self):
        agent = HilAgent()
        agent.start("blink", "code")
        self.assertIsNone(agent.feed_output("Traceback (most recent call last):"))
        self.assertIsNone(agent.command_accepted("write_file"))
        self.assertEqual(agent.command_accepted("Run").state, HilState.RUNNING)
