import unittest
from collections import Counter
from art_artwork_pipeline.path_planner.path_optimizer import balanced_cells, optimize_plan, path_length, stroke_midpoint

class TestPathOptimizer(unittest.TestCase):
    def test_balanced(self):
        self.assertEqual(sorted(Counter(balanced_cells(42)).values()), [5,5,6])
        self.assertEqual(balanced_cells(42), balanced_cells(42))
    def test_join_continuously(self):
        plan = {'schema_version':'0.2','job_id':'x','unit':'mm',
                'coordinate_frame':'paper_top_left_x_right_y_down',
                'paper_mm':{'width':210.,'height':297.}, 'seed':42,
                'grid':{'type':'4x4','cell_pen_ids':balanced_cells(42)},
                'strokes':[{'points_mm':[[12,10],[15,10]]},
                         {'points_mm':[[15.1,10],[18,10]]},
                         {'points_mm':[[190,260],[190,265]]}]}
        out=optimize_plan(plan,backend='opencv',merge_tolerance_mm=.2)
        self.assertEqual(len(out['strokes']),2)
        self.assertTrue(all(p['continuous_pen_down'] for p in out['strokes']))
        self.assertEqual([p['execution_order'] for p in out['strokes']], [0,1])
        self.assertTrue(all(out['grid']['cell_pen_ids'][p['grid_id']]==p['pen_id'] for p in out['strokes']))
        self.assertAlmostEqual(sum(path_length(p['points_mm']) for p in out['strokes']),11.0,delta=0.5)
    def test_no_cross_color_merge(self):
        # A small gap cannot cause different colors to be physically joined.
        cells=balanced_cells(42)
        a=next(i for i in range(15) if cells[i]!=cells[i+1])
        p1=[[(a%4+.4)*52.5,(a//4+.4)*74.25],[(a%4+.5)*52.5,(a//4+.4)*74.25]]
        # pick locations independently where cell colors differ
        b=next(i for i in range(16) if cells[i]!=cells[a])
        p2=[[(b%4+.4)*52.5,(b//4+.4)*74.25],[(b%4+.5)*52.5,(b//4+.4)*74.25]]
        plan={'paper_mm':{'width':210,'height':297},'seed':42,'grid':{},'strokes':[{'points_mm':p1},{'points_mm':p2}]}
        out=optimize_plan(plan,backend='opencv',merge_tolerance_mm=1.)
        self.assertEqual(len(out['strokes']),2)
        self.assertNotEqual(out['strokes'][0]['pen_id'],out['strokes'][1]['pen_id'])

if __name__=='__main__': unittest.main()
