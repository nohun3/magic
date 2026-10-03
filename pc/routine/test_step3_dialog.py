"""Hardware-free regression checks: python -m unittest pc.routine.test_step3_dialog."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


class Step3DialogTests(unittest.TestCase):
    def setUp(self):
        # Load only the polling function, avoiding OCR/serial/native imports.
        source = Path(__file__).with_name("step_move_to_wasteland.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "_wait_for_step3_dialog")
        self.capture = Mock(side_effect=[("frame1", "converter1"),
                                         ("frame2", "converter2"),
                                         ("frame3", "converter3")])
        self.hp = Mock(return_value=None)
        self.sleep = Mock()
        namespace = {"_capture_and_convert": self.capture,
                     "_step3_hp_is_critical": self.hp,
                     "sleep_jittered": self.sleep, "print": Mock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     str(source), "exec"), namespace)
        self.poll = namespace[function.name]

    def run_poll(self, locator):
        return self.poll({}, locator, Mock(), "game", Mock(), Mock(), 40.0)

    def test_late_dialog_uses_fresh_frame_and_converter(self):
        locator = Mock()
        locator.find.side_effect = [None, None, "target"]
        self.assertEqual(self.run_poll(locator), ("target", "converter3", None))
        self.assertEqual(self.capture.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_missing_dialog_is_bounded(self):
        locator = Mock()
        locator.find.return_value = None
        self.assertEqual(self.run_poll(locator), (None, "converter3", None))
        self.assertEqual(locator.find.call_count, 3)

    def test_visible_dialog_returns_immediately(self):
        locator = Mock()
        locator.find.return_value = "target"
        self.assertEqual(self.run_poll(locator), ("target", "converter1", None))
        self.sleep.assert_not_called()

    def test_hp_recovery_preempts_dialog_for_both_ack_results(self):
        for acknowledged in (True, False):
            with self.subTest(acknowledged=acknowledged):
                self.setUp()
                self.hp.return_value = acknowledged
                locator = Mock()
                self.assertEqual(self.run_poll(locator),
                                 (None, "converter1", acknowledged))
                locator.find.assert_not_called()
                self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
