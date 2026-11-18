import xml.etree.ElementTree as ET
from art_artwork_pipeline.path_planner.drawing_plan import build_plan
from art_artwork_pipeline.path_planner.svg_exporter import export_svg


def test_svg_matches_drawing_plan(tmp_path):
    strokes = [{'stroke_id': 1, 'points': [[0, 0], [50, 50]]},
               {'stroke_id': 2, 'points': [[25, 25], [70, 80]]}]
    plan = build_plan(strokes, 100, 100, seed=42)
    target = export_svg(plan, tmp_path / 'sample.svg')
    root = ET.parse(target).getroot()
    ns = {'svg': 'http://www.w3.org/2000/svg'}
    paths = root.findall('svg:path', ns)
    assert len(paths) == len(plan['strokes'])
    for element, path in zip(paths, plan['strokes']):
        assert element.get('data-pen-id') == path['pen_id']
        assert element.get('data-execution-order') == str(path['execution_order'])
        expected = 'M ' + ' L '.join(f'{x:g},{y:g}' for x, y in path['points_mm'])
        assert element.get('d') == expected
