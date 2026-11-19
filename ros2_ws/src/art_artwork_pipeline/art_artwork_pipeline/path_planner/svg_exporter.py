"""Export validated DrawingPlan paths to editable A4 SVG; no robot motion."""
from pathlib import Path
import xml.etree.ElementTree as ET
from .drawing_plan import validate_plan

SVG_NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG_NS)
PEN_COLORS = {'PEN_1': '#e53935', 'PEN_2': '#2e7d32', 'PEN_3': '#1565c0', 'PEN_4': '#111111'}


def export_svg(plan, output, stroke_width_mm=0.4):
    validate_plan(plan)
    if stroke_width_mm <= 0:
        raise ValueError('stroke_width_mm must be positive')
    width, height = plan['paper_mm']['width'], plan['paper_mm']['height']
    root = ET.Element(f'{{{SVG_NS}}}svg', {
        'width': f'{width:g}mm', 'height': f'{height:g}mm',
        'viewBox': f'0 0 {width:g} {height:g}',
        'version': '1.1', 'data-job-id': str(plan['job_id']),
        'data-coordinate-frame': plan['coordinate_frame'],
    })
    ET.SubElement(root, f'{{{SVG_NS}}}title').text = 'A4 DrawingPlan paths'
    for path in plan['strokes']:
        d = 'M ' + ' L '.join(f'{x:g},{y:g}' for x, y in path['points_mm'])
        ET.SubElement(root, f'{{{SVG_NS}}}path', {
            'd': d, 'fill': 'none',
            'stroke': PEN_COLORS.get(path['pen_id'], '#111111'),
            'stroke-width': f'{stroke_width_mm:g}',
            'stroke-linecap': 'round', 'stroke-linejoin': 'round',
            'data-pen-id': str(path['pen_id']),
            'data-layer': str(path.get('layer', 'artwork')),
            'data-stroke-id': str(path['stroke_id']),
            'data-execution-order': str(path['execution_order']),
            'data-grid-id': str(path.get('grid_id', '')),
        })
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)
    return output
