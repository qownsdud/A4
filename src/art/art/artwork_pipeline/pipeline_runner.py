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

ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')

def job_root():
    return Path(os.environ.get('ART_JOB_PLAN_ROOT', str(Path.home() / 'A4/data/jobs'))).expanduser().resolve()

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
    if stage not in ('LINEART', 'PLAN') or method not in ('cv','dl'):
        raise ValueError('지원하지 않는 처리 단계 또는 엔진입니다.')
    if paper not in ('a4', 'postcard', 'square') or detail not in ('high','medium','low'):
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
                    LineartConverterCV(LineartCVConfig(max_side=512, binarize=True, paper=paper)).convert_to_file(path, output)
                else:
                    executable = os.environ.get('ART_DL_PYTHON', sys.executable)
                    presets = {'high': (0,220,2), 'medium': (1,210,3), 'low': (2,200,5)}
                    smooth, threshold, area = presets[detail]
                    subprocess.run([executable, '-m', 'art.artwork_pipeline.lineart.cli', '--input',str(path),
                        '--method','dl','--resolution','512','--pre-smooth',str(smooth),
                        '--line-threshold',str(threshold),'--min-line-area',str(area),
                        '--binarize','--paper',paper,'--output-dir',temporary], check=True, timeout=120, capture_output=True)
                    produced = list(Path(temporary).glob('*.png'))
                    if len(produced) != 1:
                        raise RuntimeError('DL 선화 결과가 올바르지 않습니다.')
                    output = produced[0]
                _check_cancel(cancel)
                atomic_json(directory / 'job_metadata.json',dict(job_id=job_id,stage='LINEART',confirmed=False,engine=method))
                os.link(output, directory / 'lineart.png')
            return dict(job_id=job_id,lineart_path=str(directory/'lineart.png'),plan_path='',preview_path='')
        metadata = json.loads((directory / 'job_metadata.json').read_text())
        if metadata.get('job_id') != job_id or metadata.get('confirmed') is not True:
            raise ValueError('사용자가 확인한 선화만 계획으로 변환할 수 있습니다.')
        if (directory / 'drawing_plan.json').exists():
            raise FileExistsError('이미 공개된 계획은 덮어쓰지 않습니다.')
        result = extract_vector_paths(str(path))
        _check_cancel(cancel)
        feedback('VECTOR')
        payload = [{'points': [list(point) for point in stroke]} for stroke in result.strokes]
        plan = build_plan(payload, result.width, result.height,job_id=job_id,seed=seed)
        plan = optimize_plan(plan, backend='opencv', max_strokes=None, curve_step_mm=0)
        plan['strokes'].extend(generate_strokes(text))
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
