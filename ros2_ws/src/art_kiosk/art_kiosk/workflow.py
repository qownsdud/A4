"""사용자 실행 승인과 단일 현재 작업을 영속적으로 관리합니다.

파일 잠금은 웹 요청의 경쟁을 막습니다. 실제 실행 상태와 복구 판단은
JobManager가 소유하며, 응답 유실을 새 작업 등록으로 해결하지 않습니다.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from art_artwork_pipeline.calligraphy.generator import generate_strokes
from art_artwork_pipeline.paper import layout, LANDSCAPE
from art_artwork_pipeline.pipeline_runner import atomic_json, job_directory, job_root, save_photo
from art_artwork_pipeline.plan import PlanError, load_plan
from .hmi_api import (
    ControlBody, bridge_request, check_id, command_reply, manager_ready,
    observed_status, require_same_origin,
)

router = APIRouter()
TERMINAL = ('COMPLETED', 'STOPPED')
SUBMITTED = ('SUBMITTING', 'UNKNOWN_SUBMISSION', 'REGISTERED')
_PLAN_LENGTH_CACHE: dict[str, tuple[int, list[float]]] = {}


def _plan_length_progress(plan_path, completed_strokes: int) -> dict | None:
    """drawing_plan.json의 누적 선 길이(mm)를 기준으로 진행률(%)을 계산합니다."""
    try:
        stat = plan_path.stat()
    except OSError:
        return None
    key = str(plan_path)
    cached = _PLAN_LENGTH_CACHE.get(key)
    if cached is not None and cached[0] == stat.st_mtime_ns:
        cumulative = cached[1]
    else:
        try:
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        cumulative = []
        running = 0.0
        for stroke in plan.get('strokes', []):
            pts = stroke.get('points_mm', [])
            running += sum(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) for p1, p2 in zip(pts, pts[1:]))
            cumulative.append(running)
        if len(_PLAN_LENGTH_CACHE) > 8:
            _PLAN_LENGTH_CACHE.clear()
        _PLAN_LENGTH_CACHE[key] = (stat.st_mtime_ns, cumulative)

    if not cumulative:
        return None
    total_mm = cumulative[-1]
    idx = max(0, min(int(completed_strokes), len(cumulative)))
    done_mm = cumulative[idx - 1] if idx > 0 else 0.0
    pct = round((done_mm / total_mm) * 100.0, 1) if total_mm > 0 else 0.0
    return {
        'completed_length_mm': round(done_mm, 1),
        'total_length_mm': round(total_mm, 1),
        'progress_percent': pct,
    }


def state_path():
    return job_root() / '.current_workflow.json'


def read_state():
    path = state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != 1 or not isinstance(data.get('ticket'), str):
            raise ValueError('잘못된 현재 작업 기록')
        job_directory(data['job_id'])
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, '현재 작업 기록을 읽을 수 없습니다. 관리자 확인이 필요합니다.') from exc


def save_state(data):
    state_path().parent.mkdir(parents=True, exist_ok=True)
    atomic_json(state_path(), {**data, 'updated_at': time.time()})


@contextmanager
def workflow_lock():
    path = job_root() / '.workflow.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HTTPException(409, '다른 요청을 처리 중입니다. 잠시 후 현재 상태를 확인하세요.') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def check_origin(request):
    origin = request.headers.get('origin')
    if ((origin and origin != str(request.base_url).rstrip('/'))
            or request.headers.get('sec-fetch-site') == 'cross-site'):
        raise HTTPException(403, '동일 출처 요청만 허용합니다.')


def artifact(data, name):
    directory = job_directory(data['job_id'])
    path = directory / name
    if path.is_symlink() or path.resolve().parent != directory or not path.is_file():
        raise HTTPException(404, '현재 작업의 결과 파일을 찾을 수 없습니다.')
    return path


def verify_ticket(data, ticket):
    if not data or not secrets.compare_digest(data['ticket'], ticket):
        raise HTTPException(409, '입력 또는 현재 작업이 바뀌었습니다. 새 미리보기를 확인하세요.')


async def allow_replace(request, data):
    if not data:
        return
    if data['phase'] in SUBMITTED:
        try:
            status = await observed_status(request, data['job_id'])
            if status['state_confirmed'] and not status['stale'] and status['state'] not in TERMINAL:
                raise HTTPException(409, '현재 작업이 진행 중입니다. 완료 또는 중단 후 새 그림을 입력하세요.')
        except HTTPException as exc:
            if exc.status_code == 409:
                raise
            # 브리지/재시작 등으로 이전 작업 상태가 없으면 새 입력을 허용합니다.
            return
    elif data['phase'] in ('PREPARING', 'UNKNOWN_PREPARATION'):
        directory = job_directory(data['job_id'])
        if (directory / '.processing').exists():
            raise HTTPException(409, '이미지 처리가 진행 중입니다. 잠시 후 다시 시도하세요.')


async def guard_legacy_input(request):
    """이전 API도 현재 작업을 무시하고 새 입력을 만들지 못하게 합니다."""
    with workflow_lock():
        await allow_replace(request, read_state())


def guard_legacy_registration():
    if read_state():
        raise HTTPException(409, '현재 사용자 흐름에서는 사용자 화면의 그리기 버튼으로 등록하세요.')


def prepare_response(data):
    return {
        'job_id': data['job_id'], 'phase': data['phase'], 'ticket': data['ticket'],
        'preview_url': '/api/kiosk/preview', 'text': data['text'],
    }


def _validate_detail(detail: str) -> str:
    value = str(detail).strip()
    if value in ('high', 'medium', 'low'):
        return value
    if value.isdigit() and 0 <= int(value) <= 100:
        return str(int(value))
    raise HTTPException(422, '디테일은 0~100 또는 high/medium/low여야 합니다.')


@router.post('/api/kiosk/prepare')
async def prepare(
    request: Request, photo: UploadFile = File(...), text: str = Form(''),
    detail: str = Form('50'), request_id: str = Form(''), paper: str = Form(LANDSCAPE),
):
    check_origin(request)
    request_id = request_id or str(uuid.uuid4())
    check_id(request_id)
    text = text.strip()
    detail = _validate_detail(detail)
    try:
        placement=layout(paper,bool(text))
        generate_strokes(text, origin=placement['text_origin'],bounds_mm=placement['text_bounds'],paper_size_mm=placement['size'])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    method=os.environ.get('ART_LINEART_METHOD','mfl_ld')
    if method not in ('cv','dl','mfl_ld'):
        raise HTTPException(422,'지원하지 않는 선화 처리 설정입니다.')
    raw = await photo.read(20_000_001)
    photo_hash = hashlib.sha256(raw).hexdigest()
    fingerprint = hashlib.sha256(raw + b'\0' + text.encode() + b'\0' + detail.encode() + b'\0' + paper.encode() + b'\0' + method.encode()).hexdigest()
    with workflow_lock():
        previous = read_state()
        if previous and previous.get('prepare_request_id') == request_id:
            if previous.get('input_sha256') != fingerprint:
                raise HTTPException(409, '같은 준비 요청 ID에 다른 입력을 사용할 수 없습니다.')
            if previous['phase'] == 'PREVIEW':
                return prepare_response(previous)
            raise HTTPException(409, '같은 요청을 처리했습니다. 현재 작업 상태를 확인하세요.')
        await allow_replace(request, previous)
        job_id = str(uuid.uuid4())
        try:
            directory = await run_in_threadpool(save_photo, job_id, raw)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, '유효한 20 MB 이하 사진이 필요합니다.') from exc
        data = dict(
            version=1, job_id=job_id, text=text, phase='PREPARING',
            ticket=secrets.token_urlsafe(32), prepare_request_id=request_id,
            input_sha256=fingerprint, photo_sha256=photo_hash, detail=detail, paper=paper, method=method,
            created_at=time.time(), error='',
        )
        save_state(data)
        try:
            body = dict(job_id=job_id, method=method,
                        paper=paper, detail=detail)
            can_reuse = (previous and previous['phase'] == 'PREVIEW'
                         and previous.get('photo_sha256') == photo_hash
                         and previous.get('detail') == detail and previous.get('paper','a4')==paper
                         and previous.get('method')==method)
            if can_reuse:
                # 확정된 옛 계획은 수정하지 않고, 같은 선화로 새 계획을 생성합니다.
                os.link(artifact(previous, 'lineart.png'), directory / 'lineart.png')
                atomic_json(directory / 'job_metadata.json', dict(job_id=job_id, confirmed=False,
                            engine=body['method'], reused_lineart_from=previous['job_id']))
            else:
                result = await bridge_request(request, 'POST', '/bridge/artwork', body={
                    **body, 'stage': 'LINEART', 'input_path': str(directory / 'photo.png'),
                }, timeout=150.)
                if result.get('job_id') != job_id:
                    raise HTTPException(502, 'Pipeline 작업 ID가 일치하지 않습니다.')
            artifact(data, 'lineart.png')
            metadata_path = directory / 'job_metadata.json'
            metadata = json.loads(metadata_path.read_text())
            # 계획 미리보기와 사용자의 물리 실행 승인은 별개입니다.
            atomic_json(metadata_path, {**metadata, 'preview_requested': True,
                                        'confirmed': False, 'approved': False, 'text': text})
            result = await bridge_request(request, 'POST', '/bridge/artwork', body={
                **body, 'stage': 'PLAN', 'input_path': str(directory / 'lineart.png'), 'text': text,
            }, timeout=150.)
            if result.get('job_id') != job_id:
                raise HTTPException(502, 'Pipeline 작업 ID가 일치하지 않습니다.')
            plan = artifact(data, 'drawing_plan.json')
            artifact(data, 'preview.svg')
            summary = load_plan(job_id, str(plan), plan_root=job_root())
            data.update(phase='PREVIEW', sha256=summary.sha256)
            save_state(data)
            return prepare_response(data)
        except Exception as exc:
            uncertain = not isinstance(exc, HTTPException) or exc.status_code in (502, 504)
            data.update(phase='UNKNOWN_PREPARATION' if uncertain else 'PREPARE_FAILED', error=str(exc)[:300])
            save_state(data)
            raise


class DrawBody(BaseModel):
    ticket: str = Field(min_length=1, max_length=128)

    class Config:
        extra = 'forbid'


@router.get('/api/kiosk/preview')
def preview(request: Request):
    data = read_state()
    verify_ticket(data, request.headers.get('x-preview-ticket', ''))
    if data['phase'] not in ('PREVIEW', *SUBMITTED):
        raise HTTPException(409, '미리보기 준비 중입니다.')
    return FileResponse(artifact(data, 'preview.svg'), media_type='image/svg+xml')


@router.get('/api/kiosk/current/photo')
def own_photo(request: Request):
    data = read_state()
    verify_ticket(data, request.headers.get('x-preview-ticket', ''))
    return FileResponse(artifact(data, 'photo.png'), media_type='image/png')


@router.post('/api/kiosk/draw', status_code=202)
async def draw(body: DrawBody, request: Request):
    check_origin(request)
    with workflow_lock():
        data = read_state()
        verify_ticket(data, body.ticket)
        if data['phase'] == 'REGISTERED':
            return data['reply']
        if data['phase'] in ('SUBMITTING', 'UNKNOWN_SUBMISSION'):
            # 응답 유실 뒤에는 조회만 수행합니다. CreateJob을 다시 전송하지 않습니다.
            status = await observed_status(request, data['job_id'])
            if not status['state_confirmed'] or status['stale']:
                raise HTTPException(409, '등록 결과 또는 실제 상태가 미확정입니다.')
            reply = dict(accepted=True, job_id=data['job_id'], manager_state=status['state'],
                         physical_state_confirmed=False, notice='기존 작업 등록을 조회로 확인했습니다.')
            data.update(phase='REGISTERED', reply=reply)
            save_state(data)
            return reply
        if data['phase'] != 'PREVIEW':
            raise HTTPException(409, '완성된 미리보기를 먼저 확인하세요.')
        plan = artifact(data, 'drawing_plan.json')
        try:
            summary = load_plan(data['job_id'], str(plan), plan_root=job_root())
        except PlanError as exc:
            raise HTTPException(409, '실행 계획 검증에 실패했습니다.') from exc
        if summary.sha256 != data['sha256']:
            raise HTTPException(409, '미리보기 이후 계획이 변경되었습니다.')
        # 연결이 없으면 승인/전송 상태를 변경하기 전에 실패시킵니다.
        await manager_ready(request)
        metadata_path = job_directory(data['job_id']) / 'job_metadata.json'
        metadata = json.loads(metadata_path.read_text())
        atomic_json(metadata_path, {**metadata, 'confirmed': True, 'approved': True})
        data.update(phase='SUBMITTING', error='')
        save_state(data)
        try:
            response = await bridge_request(request, 'POST', '/bridge/jobs', body={
                'job_id': data['job_id'], 'plan_path': str(plan),
            })
            reply = command_reply(response, data['job_id'])
            data.update(phase='REGISTERED', reply=reply)
            save_state(data)
            return reply
        except HTTPException as exc:
            # 명시적인 등록 거절은 미리보기로 돌아가고, 전송 여부 불명은 잠급니다.
            known_rejection = (exc.status_code == 409 and isinstance(exc.detail, dict)
                               and exc.detail.get('accepted') is False)
            data.update(phase='PREVIEW' if known_rejection else 'UNKNOWN_SUBMISSION', error=str(exc.detail)[:300])
            save_state(data)
            raise
        except Exception:
            data['phase'] = 'UNKNOWN_SUBMISSION'
            save_state(data)
            raise


async def current_snapshot(request):
    data = read_state()
    if not data:
        return dict(phase='IDLE', job_id=None, text='', status=None, can_prepare=True)
    if data['phase'] in ('PREPARING', 'UNKNOWN_PREPARATION'):
        # 웹 응답만 잃어도 완료된 원자적 계획이 있으면 미리보기를 복구합니다.
        # 처리 잠금이 남거나 원격 결과가 없으면 완료를 추측하지 않습니다.
        directory = job_directory(data['job_id'])
        if (directory / 'drawing_plan.json').is_file() and not (directory / '.processing').exists():
            try:
                with workflow_lock():
                    latest = read_state()
                    if latest['job_id'] == data['job_id'] and latest['phase'] in ('PREPARING', 'UNKNOWN_PREPARATION'):
                        summary = load_plan(data['job_id'], str(artifact(data, 'drawing_plan.json')), plan_root=job_root())
                        artifact(data, 'preview.svg')
                        data.update(phase='PREVIEW', sha256=summary.sha256, error='')
                        save_state(data)
            except (HTTPException, PlanError):
                pass
    result = {key: data.get(key) for key in ('job_id', 'text', 'phase', 'error')}
    result.update(status=None, can_prepare=True)
    if data['phase'] in SUBMITTED:
        try:
            status = await observed_status(request, data['job_id'])
            length_info = _plan_length_progress(artifact(data, 'drawing_plan.json'), status['completed_strokes'])
            if length_info:
                status.update(length_info)
            result['status'] = status
            result['can_prepare'] = not (
                status['state_confirmed'] and not status['stale'] and status['state'] not in TERMINAL
            )
        except HTTPException as exc:
            result.update(can_prepare=True, status_error=str(exc.detail))
    # 준비 응답만 잃은 브라우저는 자신이 발급한 요청 ID로 티켓을 복구할 수 있습니다.
    owner = request.headers.get('x-prepare-request', '')
    if owner and secrets.compare_digest(owner, data.get('prepare_request_id', '')):
        result['prepare_request_id'] = data['prepare_request_id']
        if data['phase'] == 'PREVIEW':
            result.update(ticket=data['ticket'], preview_url='/api/kiosk/preview')
    return result


@router.get('/api/kiosk/current')
async def current(request: Request):
    return await current_snapshot(request)


@router.get('/api/admin/current', dependencies=[Depends(require_same_origin)])
async def admin_current(request: Request):
    result = await current_snapshot(request)
    if result['job_id']:
        result.update(photo_url='/api/admin/current/media/photo',
                      preview_url='/api/admin/current/media/preview')
    return result


@router.get('/api/admin/current/media/{kind}', dependencies=[Depends(require_same_origin)])
def admin_media(kind: str, request: Request):
    names = {'photo': ('photo.png', 'image/png'), 'preview': ('preview.svg', 'image/svg+xml')}
    data = read_state()
    if not data or data['job_id'] != request.headers.get('x-expected-job-id'):
        raise HTTPException(409, '현재 작업이 바뀌었습니다.')
    if kind not in names:
        raise HTTPException(404, '지원하지 않는 미디어입니다.')
    name, media_type = names[kind]
    return FileResponse(artifact(data, name), media_type=media_type)


class CurrentControl(ControlBody):
    expected_job_id: str = Field(min_length=1, max_length=64)


@router.post('/api/kiosk/current/control', dependencies=[Depends(require_same_origin)], status_code=202)
@router.post('/api/admin/current/control', dependencies=[Depends(require_same_origin)], status_code=202)
async def control(body: CurrentControl, request: Request):
    with workflow_lock():
        data = read_state()
        if not data or data['job_id'] != body.expected_job_id or data['phase'] not in SUBMITTED:
            raise HTTPException(409, '제어 대상 작업이 바뀌었거나 아직 등록되지 않았습니다.')
        status = await observed_status(request, data['job_id'])
        if status['stale']:
            raise HTTPException(409, '현재 상태가 오래되어 제어를 중계하지 않았습니다.')
        if not status['state_confirmed'] and status['state'] not in ('FORCE_STOPPED', 'RECOVERY_REQUIRED'):
            raise HTTPException(409, '현재 상태가 미확정이어서 제어를 중계하지 않았습니다.')
        response = await bridge_request(request, 'POST', f"/bridge/jobs/{data['job_id']}/control", body={
            'command': body.command, 'request_id': body.request_id,
        })
        return command_reply(response, data['job_id'])
