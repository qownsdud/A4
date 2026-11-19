"""Export validated DrawingPlan paths to editable A4 SVG; no robot motion."""
from pathlib import Path
import xml.etree.ElementTree as ET
from .drawing_plan import validate_plan
from ..calligraphy.generator import MAX_THICKNESS_Z_DELTA_MM, MIN_THICKNESS_Z_DELTA_MM

SVG_NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG_NS)
PEN_COLORS = {'PEN_1': '#e53935', 'PEN_2': '#2e7d32', 'PEN_3': '#1565c0', 'PEN_4': '#111111'}
CALLIGRAPHY_MIN_WIDTH_MM = 0.35
CALLIGRAPHY_MAX_WIDTH_MM = 1.95


def _z_delta_to_preview_width(dz: float, fallback_width_mm: float) -> float:
    """캘리그라피 Z 오프셋(+0.7mm=최소 굵기 ~ -1.3mm=최대 굵기)을 SVG 선 굵기(mm)로 변환합니다."""
    span = MIN_THICKNESS_Z_DELTA_MM - MAX_THICKNESS_Z_DELTA_MM
    if span <= 1e-6:
        return fallback_width_mm
    norm = max(0.0, min(1.0, (MIN_THICKNESS_Z_DELTA_MM - float(dz)) / span))
    return CALLIGRAPHY_MIN_WIDTH_MM + (CALLIGRAPHY_MAX_WIDTH_MM - CALLIGRAPHY_MIN_WIDTH_MM) * norm


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
        pts = path['points_mm']
        z_deltas = path.get('z_deltas_mm')
        stroke_color = PEN_COLORS.get(path['pen_id'], '#111111')
        base_attrs = {
            'data-pen-id': str(path['pen_id']),
            'data-layer': str(path.get('layer', 'artwork')),
            'data-stroke-id': str(path['stroke_id']),
            'data-execution-order': str(path['execution_order']),
            'data-grid-id': str(path.get('grid_id', '')),
        }
        has_variable_width = (
            isinstance(z_deltas, list)
            and len(z_deltas) == len(pts)
            and len(pts) >= 2
            and any(abs(float(v) - float(z_deltas[0])) > 1e-4 or abs(float(v)) > 1e-4 for v in z_deltas)
        )
        if has_variable_width:
            group = ET.SubElement(root, f'{{{SVG_NS}}}g', {
                'fill': 'none',
                'stroke': stroke_color,
                'stroke-linecap': 'round',
                'stroke-linejoin': 'round',
                **base_attrs,
            })
            for i in range(len(pts) - 1):
                x0, y0 = pts[i]
                x1, y1 = pts[i + 1]
                seg_dz = 0.5 * (float(z_deltas[i]) + float(z_deltas[i + 1]))
                seg_w = _z_delta_to_preview_width(seg_dz, stroke_width_mm)
                ET.SubElement(group, f'{{{SVG_NS}}}path', {
                    'd': f'M {x0:g},{y0:g} L {x1:g},{y1:g}',
                    'stroke-width': f'{seg_w:.3g}',
                })
        else:
            d = 'M ' + ' L '.join(f'{x:g},{y:g}' for x, y in pts)
            ET.SubElement(root, f'{{{SVG_NS}}}path', {
                'd': d, 'fill': 'none',
                'stroke': stroke_color,
                'stroke-width': f'{stroke_width_mm:g}',
                'stroke-linecap': 'round', 'stroke-linejoin': 'round',
                **base_attrs,
            })
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)
    return output
