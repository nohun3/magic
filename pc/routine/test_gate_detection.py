"""Hardware-free gate regression checks."""
import ast
from pathlib import Path
from typing import List, Optional, Tuple
import unittest
from unittest.mock import Mock, patch
import cv2
import numpy as np
from pc.capture.screen_capture import Region
from pc.detector.template_locator import MatchResult

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'pc/routine/step_move_to_wasteland.py'
NAMES = {'locate_teleport_gate', '_partial_gate_match',
         '_visible_gate_template', 'find_gate_safe_click_points'}
namespace = dict(cv2=cv2, np=np, Region=Region, MatchResult=MatchResult,
                 List=List, Optional=Optional, Tuple=Tuple, Path=Path)
tree = ast.parse(SOURCE.read_text(encoding='utf8'))
exec(compile(ast.Module(body=[n for n in tree.body
     if isinstance(n, ast.FunctionDef) and n.name in NAMES],
     type_ignores=[]), str(SOURCE), 'exec'), namespace)


class GateDetectionTests(unittest.TestCase):
    def test_rejected_peak_does_not_hide_next_candidate(self):
        scores = np.zeros((100, 100), np.float32)
        scores[5, 5] = .456
        scores[70, 70] = .401
        validator = Mock(side_effect=[[], [(75., 75.)]])
        settings = {'npcs': {'teleport_gate': {
            'template': 'unused', 'match_threshold': .35}}}
        with patch.object(cv2, 'imread', return_value=np.ones((10, 10, 3), np.uint8)), \
             patch.object(cv2, 'matchTemplate', return_value=scores), \
             patch.dict(namespace, find_gate_safe_click_points=validator):
            match = namespace['locate_teleport_gate'](
                settings, ROOT, np.zeros((109, 109, 3), np.uint8))
        self.assertEqual(match.region, Region(70, 70, 10, 10))
        self.assertEqual(validator.call_count, 2)

    def test_partial_match_is_also_validated(self):
        frame = np.zeros((20, 20, 3), np.uint8)
        template = np.zeros((8, 8, 3), np.uint8)
        validator = Mock(return_value=False)
        match = namespace['_partial_gate_match'](
            frame, template, .5, .5, 2, candidate_validator=validator)
        self.assertIsNone(match)
        self.assertGreater(validator.call_count, 0)

    def test_saved_cliff_false_positive_selects_actual_gate(self):
        path = ROOT / 'output/gate_preclick/gate_preclick_1793371227767_attempt05_score0456_x8_y200.png'
        if not path.exists():
            self.skipTest('Local captured failure frame is unavailable')
        frame = cv2.imread(str(path))
        settings = {'npcs': {'teleport_gate': {
            'template': 'templates/npc_teleport_gate.png', 'match_threshold': .35}}}
        match = namespace['locate_teleport_gate'](settings, ROOT, frame)
        self.assertIsNotNone(match)
        self.assertEqual(match.region, Region(677, 399, 154, 199))
        points = namespace['find_gate_safe_click_points'](
            frame, cv2.imread(str(ROOT / settings['npcs']['teleport_gate']['template'])),
            match.region, {})
        self.assertTrue(points)


if __name__ == '__main__':
    unittest.main()
