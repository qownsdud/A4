import unittest
from art_artwork_pipeline.path_planner.drawing_plan import build_plan, validate_plan

class PlanTests(unittest.TestCase):
    def test_repeatable_color_and_bounds(self):
        strokes = [{'stroke_id': 1, 'points': [[0, 0], [99, 99]]},
                   {'stroke_id': 2, 'points': [[99, 0], [0, 99]]}]
        a = build_plan(strokes, 100, 100, job_id='sample', seed=17)
        b = build_plan(strokes, 100, 100, job_id='sample', seed=17)
        self.assertEqual(a, b)
        self.assertTrue(validate_plan(a))
        self.assertEqual([p['execution_order'] for p in a['strokes']], [0, 1])
    def test_reject_outside(self):
        with self.assertRaises(ValueError):
            build_plan([{'points': [[0,0],[101,5]]}], 100, 100)
    def test_reject_nan(self):
        with self.assertRaises(ValueError):
            build_plan([{'points': [[0,0],[float('nan'),5]]}], 100, 100)

if __name__ == '__main__':
    unittest.main()
