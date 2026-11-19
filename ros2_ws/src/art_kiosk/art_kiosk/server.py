"""사용자 사진·문구 입력과 자동 경로 미리보기, 관리자 HMI를 제공하는 서버."""

from __future__ import annotations

import io
import json
from pathlib import Path
import time

import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
import os
import uuid
from fastapi import Request, Depends
from pydantic import BaseModel, Field
from .preprocess import normalize_photo_bytes
from .hmi_api import router as hmi_router, bridge_request, require_same_origin
from art_artwork_pipeline.lineart.utils import PAPER_RATIOS
from art_artwork_pipeline.pipeline_runner import job_root, job_directory, save_photo, atomic_json

app = FastAPI(
    title="카메라 라인아트 협동로봇 키오스크",
    description="사진과 영문 문구의 경로를 자동 생성하고 사용자 그리기 승인 후 작업을 등록합니다.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(hmi_router)
from .workflow import router as workflow_router
app.include_router(workflow_router)


@app.middleware("http")
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' blob: data:; media-src 'self' blob:; "
        "connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
    )
    return response


def _compute_black_ratio(png_bytes: bytes) -> float:
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if gray is None or gray.size == 0:
        return 0.0
    return float(np.mean(gray < 128))


DL_DETAIL_PRESETS: dict[str, dict[str, object]] = {
    "high": {
        "label": "세밀하게 (디테일 많이)",
        "coarse": False,
        "pre_smooth": 0,
        "line_threshold": 220,
        "min_line_area": 2,
    },
    "medium": {
        "label": "표준 (균형)",
        "coarse": False,
        "pre_smooth": 1,
        "line_threshold": 210,
        "min_line_area": 3,
    },
    "low": {
        "label": "단순하게 (굵은 선 위주)",
        "coarse": False,
        "pre_smooth": 2,
        "line_threshold": 200,
        "min_line_area": 5,
    },
}


@app.get("/")
def serve_kiosk_ui() -> FileResponse:
    """Serve the camera-only kiosk frontend."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def api_health():
    return {"status": "ok", "engine": os.environ.get("ART_LINEART_METHOD", "mfl_ld"),
            "dl_ready": False, "notice": "모델 추론과 ROS 연결은 별도 확인이 필요합니다."}


async def request_pipeline(request, body):
    return await bridge_request(request, "POST", "/bridge/artwork", body=body, timeout=150.)


@app.post("/api/kiosk/photo")
async def kiosk_photo_to_lineart(request: Request, photo: UploadFile = File(...),
        detail: str = Form("medium"), paper: str = Form("a4")):
    from .workflow import guard_legacy_input
    await guard_legacy_input(request)
    if paper not in PAPER_RATIOS or detail not in DL_DETAIL_PRESETS:
        raise HTTPException(400, "지원하지 않는 용지 또는 디테일입니다.")
    job_id = str(uuid.uuid4())
    try:
        raw = await photo.read(20_000_001)
        directory = await run_in_threadpool(save_photo, job_id, raw)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, "유효한 20 MB 이하 이미지가 필요합니다.") from exc
    started = time.perf_counter()
    method = os.environ.get("ART_LINEART_METHOD", "mfl_ld")
    result = await request_pipeline(request, dict(job_id=job_id,stage="LINEART",
        input_path=str(directory/'photo.png'),method=method,paper=paper,detail=detail))
    expected = directory/'lineart.png'
    if result.get('job_id') != job_id or result.get('lineart_path') != str(expected) or not expected.is_file() or expected.is_symlink():
        raise HTTPException(502, "Pipeline 결과 경로가 일치하지 않습니다.")
    content = expected.read_bytes()
    with Image.open(io.BytesIO(content)) as image:
        width,height = image.size
    return Response(content,media_type="image/png",headers={
        "X-Job-Id":job_id,"X-Elapsed-Sec":f"{time.perf_counter()-started:.2f}",
        "X-Black-Ratio":f"{_compute_black_ratio(content):.4f}",
        "X-Image-Size":f"{width}x{height}","X-Engine":f"{method} ({detail})"})


@app.post("/api/kiosk/confirm")
async def confirm_lineart_for_robot(image: UploadFile = File(...),paper: str = Form("a4"),
        engine: str = Form("unknown"),job_id: str = Form("")):
    raw = await image.read(20_000_001)
    if not raw or len(raw)>20_000_000 or paper not in PAPER_RATIOS:
        raise HTTPException(400, "이미지 또는 용지 설정이 잘못되었습니다.")
    try:
        clean = normalize_photo_bytes(raw,max_side=1024)
        if job_id:
            directory = job_directory(job_id)
            # 선화 생성 후 확인만 허용합니다. 원본 선화를 교체하지 않습니다.
            with Image.open(io.BytesIO(raw)) as supplied, Image.open(directory/'lineart.png') as actual:
                if supplied.convert('RGB').size != actual.size or supplied.convert('RGB').tobytes() != actual.convert('RGB').tobytes():
                    raise ValueError('생성된 선화와 확인 이미지가 다릅니다.')
        else:
            job_id = str(uuid.uuid4())
            directory = job_directory(job_id)
            directory.mkdir(parents=True,exist_ok=False)
            (directory/'lineart.png').write_bytes(clean)
        metadata_path = directory/'job_metadata.json'
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        if (directory/'drawing_plan.json').exists():
            raise ValueError('계획 생성 이후 확인 상태는 변경할 수 없습니다.')
        atomic_json(metadata_path,{**metadata,'job_id':job_id,'confirmed':True,'stage':'CONFIRMED','paper':paper,'engine':engine})
        atomic_json(job_root()/'latest.json',{'job_id':job_id})
        with Image.open(directory/'lineart.png') as im:
            width,height=im.size
    except (OSError,ValueError) as exc:
        raise HTTPException(400, "유효한 작업별 선화가 필요합니다.") from exc
    return dict(status='confirmed',job_id=job_id,drawing_plan_created=False,job_started=False,
        message='선화를 확인했습니다. 계획 생성 및 관리자 승인은 별도 단계입니다.',
        latest_file=str(directory/'lineart.png'),archived_previous_file=None,width=width,height=height)


@app.get('/api/kiosk/latest')
def get_latest_confirmed():
    try:
        job_id=json.loads((job_root()/'latest.json').read_text())['job_id']
        path=job_directory(job_id)/'lineart.png'
        with Image.open(path) as image:
            return dict(job_id=job_id,latest_file=str(path),width=image.width,height=image.height)
    except (OSError,ValueError,KeyError) as exc:
        raise HTTPException(404,'확인된 선화가 없습니다.') from exc


class PlanOptions(BaseModel):
    text: str = Field(default='',max_length=120)
    seed: int = 42
    class Config:
        extra = 'forbid'


@app.post('/api/admin/artwork/{job_id}/prepare', dependencies=[Depends(require_same_origin)])
async def prepare_plan(job_id: str, request: Request, options: PlanOptions = PlanOptions()):
    try:
        directory=job_directory(job_id)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return await request_pipeline(request,dict(job_id=job_id,stage='PLAN',
        input_path=str(directory/'lineart.png'),method='cv',paper='a4',detail='medium',
        text=options.text,seed=options.seed))
