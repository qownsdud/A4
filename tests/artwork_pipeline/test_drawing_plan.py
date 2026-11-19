import unittest
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, validate_plan
from art_artwork_pipeline.puzzle.colors import assign_stroke_pens

class PlanTests(unittest.TestCase):
    def test_repeatable_color_and_bounds(self):
        strokes = [{'stroke_id': 1, 'points': [[0, 0], [99, 99]]},
                   {'stroke_id': 2, 'points': [[99, 0], [0, 99]]}]
        a = build_plan(strokes, 100, 100, job_id='sample', seed=17)
        b = build_plan(strokes, 100, 100, job_id='sample', seed=17)
        self.assertEqual(a, b)
        self.assertTrue(validate_plan(a))
        self.assertEqual([p['execution_order'] for p in a['strokes']], [0, 1])
    def test_stroke_color_diversification_and_balance(self):
        strokes = [[[10 + i * 15, 20], [10 + i * 15, 60]] for i in range(12)]
        pens_a = assign_stroke_pens(strokes, seed=42)
        pens_b = assign_stroke_pens(strokes, seed=7)
        self.assertEqual(set(pens_a), {'PEN_1', 'PEN_2', 'PEN_3'})
        self.assertEqual(len(pens_a), 12)
        self.assertEqual(pens_a.count('PEN_1'), 4)
        self.assertEqual(pens_a.count('PEN_2'), 4)
        self.assertEqual(pens_a.count('PEN_3'), 4)
        self.assertNotEqual(pens_a, pens_b)
    def test_split_long_stroke_changes_colors_along_path(self):
        plan = build_plan(
            [{'points': [[0, 50], [99, 50]]}],
            100, 100, job_id='split_long', seed=42, max_stroke_mm=55.0,
        )
        self.assertGreaterEqual(len(plan['strokes']), 3)
        self.assertTrue(validate_plan(plan))
        self.assertGreaterEqual(len({s['pen_id'] for s in plan['strokes']}), 2)
    def test_reject_outside(self):
        with self.assertRaises(ValueError):
            build_plan([{'points': [[0,0],[101,5]]}], 100, 100)
    def test_reject_nan(self):
        with self.assertRaises(ValueError):
            build_plan([{'points': [[0,0],[float('nan'),5]]}], 100, 100)

if __name__ == '__main__':
    unittest.main()
