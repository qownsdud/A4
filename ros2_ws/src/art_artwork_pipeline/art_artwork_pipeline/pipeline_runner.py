"""ROS와 독립된 작업 처리. 사진·선화·계획의 확인 경계를 분리합니다."""
from pathlib import Path
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from PIL import Image, ImageOps
from .lineart.lineart_cv import LineartCVConfig, LineartConverterCV
from .path_planner.extractor import extract_vector_paths
from .path_planner.drawing_plan import build_plan, validate_plan, write_job_plan
from .path_planner.path_optimizer import optimize_plan
from .path_planner.svg_exporter import export_svg
from .calligraphy.generator import generate_strokes
from .paper import layout, LANDSCAPE, fit_landscape_preview

ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')

def a4_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == 'ros2_ws':
            return parent.parent
    return Path.cwd()


def job_root():
    return Path(os.environ.get('ART_JOB_PLAN_ROOT', str(a4_root() / 'data/jobs'))).expanduser().resolve()

def job_directory(job_id, root=None):
    if not isinstance(job_id, str) or not ID.fullmatch(job_id):
        raise ValueError('잘못된 작업 ID입니다.')
    root = Path(root or job_root()).resolve()
    directory = root / job_id
    if directory.resolve().parent != root:
        raise ValueError('작업 디렉터리가 허용 루트를 벗어납니다.')
    return directory

def atomic_json(path, data):
    path = Path(path)
    fd, staged = tempfile.mkstemp(dir=path.parent, prefix='.metadata_')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)

def save_photo(job_id, raw, root=None):
    if len(raw) > 20_000_000:
        raise ValueError('사진은 20 MB 이하여야 합니다.')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 25_000_000:
            raise ValueError('사진 해상도가 너무 큽니다.')
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((1024, 1024))
        directory = job_directory(job_id, root)
        directory.mkdir(parents=True, exist_ok=False)
        image.save(directory / 'photo.png')
    return directory

def _check_cancel(cancel):
    if cancel():
        raise InterruptedError('사용자가 이미지 처리를 취소했습니다.')

def prepare_artwork(job_id, *, stage, input_path, root=None, method='cv', paper='a4',
                    detail='medium', seed=42, text='', cancel=lambda: False,
                    feedback=lambda stage: None):
    """단계: LINEART → 명시적 사용자 확인 → PLAN. 작업 등록/실행은 하지 않습니다.

    취소는 알고리즘 단계 사이에서 처리합니다. 완료 파일 공개 이후에는 성공을 반환합니다.
    DL은 ART_DL_PYTHON으로 지정한 환경에서 동일한 설치 패키지를 실행합니다.
    """
    directory = job_directory(job_id, root)
    if stage not in ('LINEART', 'PLAN') or method not in ('cv','dl','mfl_ld'):
        raise ValueError('지원하지 않는 처리 단계 또는 엔진입니다.')
    if paper not in ('a4', LANDSCAPE, 'postcard', 'square') or detail not in ('high','medium','low'):
        raise ValueError('지원하지 않는 용지 또는 디테일입니다.')
    expected = directory / ('photo.png' if stage == 'LINEART' else 'lineart.png')
    path = Path(input_path)
    if not path.is_absolute() or path.resolve(strict=True) != expected or expected.is_symlink():
        raise ValueError('작업별 허용 입력 파일만 읽을 수 있습니다.')
    # 프로세스 간에도 같은 작업은 동시에 처리하지 않습니다. 실패/취소 시 잠금을 해제합니다.
    lock = directory / '.processing'
    with lock.open('x'):
        pass
    try:
        _check_cancel(cancel)
        feedback(stage)
        if stage == 'LINEART':
            if (directory / 'lineart.png').exists():
                raise FileExistsError('이미 생성된 선화는 덮어쓰지 않습니다.')
            with tempfile.TemporaryDirectory(dir=directory) as temporary:
                output = Path(temporary) / 'lineart.png'
                if method == 'cv':
                    LineartConverterCV(LineartCVConfig(max_side=512, binarize=True, paper=None if paper==LANDSCAPE else paper)).convert_to_file(path, output)
                else:
                    default_python=Path.home()/'.venvs/a4-lineart/bin/python'
                    executable = os.environ.get('ART_DL_PYTHON',str(default_python) if default_python.is_file() else sys.executable)
                    presets = {'high': (0,220,2), 'medium': (1,210,3), 'low': (2,200,5)}
                    smooth, threshold, area = presets[detail]
                    try:
                        subprocess.run([executable, '-m', 'art_artwork_pipeline.lineart.cli', '--input',str(path),
                            '--method',method,'--resolution','512','--pre-smooth',str(smooth),
                            '--line-threshold',str(threshold),'--min-line-area',str(area),
                            '--binarize','--paper','none' if paper==LANDSCAPE else paper,'--output-dir',temporary], check=True, timeout=120, capture_output=True)
                    except subprocess.CalledProcessError as exc:
                        detail=(exc.stderr or b'').decode('utf-8',errors='replace').splitlines()
                        raise RuntimeError('선화 모델 실행 실패: '+(detail[-1] if detail else str(exc))) from exc
                    produced = list(Path(temporary).glob('*.png'))
                    if len(produced) != 1:
                        raise RuntimeError('DL 선화 결과가 올바르지 않습니다.')
                    output = produced[0]
                if paper==LANDSCAPE:
                    with Image.open(output) as image:
                        fitted=fit_landscape_preview(image)
                    fitted.save(output)
                _check_cancel(cancel)
                atomic_json(directory / 'job_metadata.json',dict(job_id=job_id,stage='LINEART',confirmed=False,engine=method))
                os.link(output, directory / 'lineart.png')
            return dict(job_id=job_id,lineart_path=str(directory/'lineart.png'),plan_path='',preview_path='')
        metadata = json.loads((directory / 'job_metadata.json').read_text())
        if metadata.get('job_id') != job_id or not (
                metadata.get('confirmed') is True or metadata.get('preview_requested') is True):
            raise ValueError('사용자가 확인하거나 미리보기 요청한 선화만 계획으로 변환할 수 있습니다.')
        if (directory / 'drawing_plan.json').exists():
            raise FileExistsError('이미 공개된 계획은 덮어쓰지 않습니다.')
        # 샘플 기준(2. Balanced: len>=8.0, eps=1.5, gap=4.5)에 맞춰 불필요한 꼭짓점·잡선 제거
        result = extract_vector_paths(
            str(path),
            epsilon=1.5,
            min_length_px=8.0,
            bridge_gap_px=4.5,
            preserve_thick_contours=False,
            smooth_iterations=0,
        )
        _check_cancel(cancel)
        feedback('VECTOR')
        payload = [{'points': [list(point) for point in stroke]} for stroke in result.strokes]
        placement=layout(paper, bool(text))
        # 가로 선화에는 20mm 여백이 이미 있습니다. 글씨가 없으면 전체 종이로 매핑해 이중 여백을 피합니다.
        box=placement['artwork']
        if paper==LANDSCAPE:
            # 내부 그림 영역을 다시 전체 그림 좌표로 환산한 뒤 확정된 배치 영역에만 맞춥니다.
            payload=[{'points':[[max(0.,min(771.,x-60)),max(0.,min(510.,y-60))]
                                for x,y in item['points']]} for item in payload]
            width,height=772,511
        else:
            width,height=result.width,result.height
        plan = build_plan(payload, width, height, job_id=job_id, seed=seed,
                          paper_size_mm=placement['size'], margin_mm=placement['margin'],artwork_box_mm=box)
        # 앞단 픽셀 단순화(eps=1.5) 결과를 유지하기 위해 mm 재단순화는 비활성화
        plan = optimize_plan(plan, backend='opencv', simplify_tolerance_mm=0.0, max_strokes=None, curve_step_mm=0)
        plan['strokes'].extend(generate_strokes(text, origin=placement['text_origin'], bounds_mm=placement['text_bounds'],paper_size_mm=placement['size']))
        for i, stroke in enumerate(plan['strokes']):
            stroke.update(stroke_id=i+1,execution_order=i)
        validate_plan(plan)
        _check_cancel(cancel)
        feedback('PREVIEW')
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            svg = export_svg(plan, Path(temporary)/'preview.svg')
            _check_cancel(cancel)
            # 계획 파일을 마지막에 원자적으로 공개합니다. 그 이전 파일은 완료 증거가 아닙니다.
            os.replace(svg, directory/'preview.svg')
            atomic_json(directory/'job_metadata.json', {**metadata,'stage':'PREPARED','approved':False})
            published = write_job_plan(plan, directory.parent)
        return dict(job_id=job_id,lineart_path=str(path),plan_path=str(published),preview_path=str(directory/'preview.svg'))
    finally:
        lock.unlink()
