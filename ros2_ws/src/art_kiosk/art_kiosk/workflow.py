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
_PLAN_PROFILE_CACHE: dict[str, tuple[int, dict]] = {}
_JOB_TIMING: dict[str, dict] = {}
_DEFAULT_LINEART_SEC = 7.0
_DEFAULT_PLAN_SEC = 3.5
_CMD_OVERHEAD_SEC = 0.055


def _prepare_timing_path():
    return job_root() / '.prepare_timing.json'


def get_prepare_timing_estimate() -> dict:
    """과거 선화/경로 생성 소요 시간 EMA 기록을 바탕으로 예상 대기 시간(초)을 반환합니다."""
    lineart_sec = _DEFAULT_LINEART_SEC
    plan_sec = _DEFAULT_PLAN_SEC
    try:
        raw = json.loads(_prepare_timing_path().read_text(encoding='utf-8'))
        lv = float(raw.get('lineart_sec', lineart_sec))
        pv = float(raw.get('plan_sec', plan_sec))
        if math.isfinite(lv) and 1.0 <= lv <= 90.0:
            lineart_sec = lv
        if math.isfinite(pv) and 0.5 <= pv <= 60.0:
            plan_sec = pv
    except (OSError, ValueError, TypeError):
        pass
    return {
        'lineart_sec': round(lineart_sec, 1),
        'plan_sec': round(plan_sec, 1),
        'total_sec': round(lineart_sec + plan_sec, 1),
    }


def _record_prepare_timing(key: str, elapsed_sec: float) -> None:
    if not math.isfinite(elapsed_sec) or elapsed_sec < 0.3 or elapsed_sec > 120.0:
        return
    est = get_prepare_timing_estimate()
    prev = est.get(key, _DEFAULT_LINEART_SEC if key == 'lineart_sec' else _DEFAULT_PLAN_SEC)
    updated = 0.65 * prev + 0.35 * elapsed_sec
    data = {'lineart_sec': est['lineart_sec'], 'plan_sec': est['plan_sec']}
    data[key] = round(updated, 2)
    try:
        path = _prepare_timing_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, data)
    except OSError:
        pass


def _compute_prepare_progress(data: dict) -> dict:
    """PREPARING 상태의 현재 단계·진행률(%)·남은 예상 시간(초)을 계산합니다."""
    now = time.time()
    stage = str(data.get('prepare_stage') or 'LINEART')
    started = float(data.get('prepare_started_at') or data.get('created_at') or now)
    stage_started = float(data.get('prepare_stage_started_at') or started)
    est_lineart = max(1.0, float(data.get('prepare_est_lineart_sec') or _DEFAULT_LINEART_SEC))
    est_plan = max(0.5, float(data.get('prepare_est_plan_sec') or _DEFAULT_PLAN_SEC))
    reused = bool(data.get('prepare_reused_lineart', False))
    elapsed = max(0.0, now - started)
    stage_elapsed = max(0.0, now - stage_started)

    if stage == 'PLAN':
        stage_label = '경로 추출 및 최적화 중'
        base_pct = 12.0 if reused else 78.0
        span_pct = 96.0 - base_pct
        frac = stage_elapsed / est_plan
        if frac <= 1.0:
            pct = base_pct + span_pct * frac
        else:
            pct = 96.0 + 2.5 * (1.0 - math.exp(-(frac - 1.0)))
        rem = max(1.0, est_plan - stage_elapsed) if frac < 0.95 else 1.0
        total = est_plan if reused else (est_lineart + est_plan)
    else:
        stage_label = '선화 변환 중 (MFL-LD)'
        frac = stage_elapsed / est_lineart
        if frac <= 1.0:
            pct = 4.0 + 72.0 * frac
        else:
            pct = 76.0 + 8.0 * (1.0 - math.exp(-(frac - 1.0)))
        rem_lineart = max(1.0, est_lineart - stage_elapsed) if frac < 0.95 else 1.5
        rem = rem_lineart + est_plan
        total = est_lineart + est_plan

    return {
        'stage': stage,
        'stage_label': stage_label,
        'percent': round(min(98.5, max(2.0, pct)), 1),
        'remaining_sec': round(max(1.0, rem), 1),
        'total_sec': round(total, 1),
        'elapsed_sec': round(elapsed, 1),
    }


def _motion_profile_settings() -> dict:
    defaults = dict(
        travel_velocity=150.0,
        travel_acceleration=220.0,
        draw_velocity=82.5,
        draw_acceleration=200.0,
        pen_down_velocity=65.0,
        pen_down_acceleration=180.0,
        pick_velocity=40.0,
        pick_acceleration=80.0,
        stroke_lift_mm=4.0,
        group_lift_mm=15.0,
        slot_approach_mm=100.0,
        corner_angle_deg=55.0,
        spline_max_points=80,
        spline_vel_scale=0.85,
        spline_max_lateral_acc=320.0,
        spline_min_velocity=35.0,
        spline_min_acceleration=80.0,
    )
    try:
        from art_drawing_controller.equipment_settings import load_default_equipment_settings
        cfg = load_default_equipment_settings()
        for key in defaults:
            if key in cfg and isinstance(cfg[key], (int, float)):
                defaults[key] = float(cfg[key])
    except Exception:
        pass
    return defaults


def _trap_move_sec(dist_mm: float, vel: float, acc: float, overhead: float = _CMD_OVERHEAD_SEC) -> float:
    if dist_mm <= 1e-6:
        return 0.0
    vel = max(1.0, float(vel))
    acc = max(1.0, float(acc))
    d_full = (vel * vel) / acc
    if dist_mm >= d_full:
        t = dist_mm / vel + vel / acc
    else:
        t = 2.0 * math.sqrt(dist_mm / acc)
    return t + overhead


def _split_corners_est(points: list, angle_deg: float = 55.0, min_arm_mm: float = 1.2) -> list:
    if len(points) < 3:
        return [points]
    parts = []
    current = points[:2]
    for i in range(1, len(points) - 1):
        ax, ay = points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]
        bx, by = points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]
        na, nb = math.hypot(ax, ay), math.hypot(bx, by)
        corner = (
            na >= min_arm_mm
            and nb >= min_arm_mm
            and math.degrees(math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb))))) >= angle_deg
        )
        if corner:
            parts.append(current)
            current = [points[i], points[i + 1]]
        else:
            current.append(points[i + 1])
    parts.append(current)
    return parts


def _estimate_plan_profile(plan_path) -> dict | None:
    """drawing_plan.json의 선 길이·모서리 분할·이격/이동/하강·펜 교체 시간을 물리 기반으로 계산합니다."""
    try:
        stat = plan_path.stat()
    except OSError:
        return None
    key = str(plan_path)
    cached = _PLAN_PROFILE_CACHE.get(key)
    if cached is not None and cached[0] == stat.st_mtime_ns:
        return cached[1]
    try:
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    strokes = plan.get('strokes', [])
    if not strokes:
        return None

    cfg = _motion_profile_settings()
    l_vel, l_acc = cfg['travel_velocity'], cfg['travel_acceleration']
    d_vel, d_acc = cfg['draw_velocity'], cfg['draw_acceleration']
    pd_vel, pd_acc = cfg['pen_down_velocity'], cfg['pen_down_acceleration']
    p_vel, p_acc = cfg['pick_velocity'], cfg['pick_acceleration']
    lift_mm = cfg['stroke_lift_mm']
    group_lift = cfg['group_lift_mm']
    approach_mm = cfg['slot_approach_mm']
    corner_deg = cfg['corner_angle_deg']
    max_pts = max(2, int(cfg['spline_max_points']))

    # 기준 막대 접촉 측정 + 홈 이동 사전 준비 시간 (약 30초)
    pre_cal_sec = 30.0
    # 마지막 펜 반납 + 홈 복귀 시간
    slot_vertical = 2.0 * _trap_move_sec(approach_mm, p_vel, p_acc) + 0.55
    pen_return_sec = _trap_move_sec(group_lift, l_vel, l_acc) + _trap_move_sec(220.0, l_vel, l_acc) + slot_vertical
    pen_pick_sec = 0.55 + _trap_move_sec(160.0, l_vel, l_acc) + slot_vertical + _trap_move_sec(220.0, l_vel, l_acc)
    finish_sec = pen_return_sec + 2.2

    plunge_sec = _trap_move_sec(lift_mm, pd_vel, pd_acc)
    lift_sec = _trap_move_sec(lift_mm, l_vel, l_acc)

    cum_length = []
    cum_time = []
    running_len = 0.0
    running_sec = 0.0
    prev_pen = None
    prev_end = None

    for stroke in strokes:
        pts = stroke.get('points_mm', [])
        if len(pts) < 2:
            cum_length.append(running_len)
            cum_time.append(running_sec)
            continue
        pen = stroke.get('pen_id', 'PEN_1')
        s_time = 0.0

        if pen != prev_pen:
            if prev_pen is not None:
                s_time += pen_return_sec
            s_time += pen_pick_sec
            prev_pen = pen
            prev_end = None

        # 직전 획 끝점에서 현재 획 시작점 위(lift_mm)로 공중 이동
        if prev_end is not None:
            travel_d = math.hypot(pts[0][0] - prev_end[0], pts[0][1] - prev_end[1])
            s_time += _trap_move_sec(travel_d, l_vel, l_acc)
        else:
            s_time += _trap_move_sec(max(1.0, group_lift - lift_mm), l_vel, l_acc)

        # 종이 터치다운 하강
        s_time += plunge_sec

        # 그리기 구간 (모서리 분할 + 곡률 적응형 스플라인 속도·가속도 반영)
        stroke_len = 0.0
        for seg in _split_corners_est(pts, corner_deg):
            targets = seg[1:]
            prev_pt = seg[0]
            for start in range(0, len(targets), max_pts):
                chunk = targets[start : start + max_pts]
                chunk_len = 0.0
                p_prev = prev_pt
                for pt in chunk:
                    chunk_len += math.hypot(pt[0] - p_prev[0], pt[1] - p_prev[1])
                    p_prev = pt
                stroke_len += chunk_len
                c_vel, c_acc = d_vel, d_acc
                if len(chunk) > 1:
                    c_pts = [prev_pt] + list(chunk)
                    total_ang = 0.0
                    ks = []
                    prev_sign = 0
                    reversals = 0
                    for i_c in range(1, len(c_pts) - 1):
                        ax, ay = c_pts[i_c][0] - c_pts[i_c - 1][0], c_pts[i_c][1] - c_pts[i_c - 1][1]
                        bx, by = c_pts[i_c + 1][0] - c_pts[i_c][0], c_pts[i_c + 1][1] - c_pts[i_c][1]
                        cx, cy = c_pts[i_c + 1][0] - c_pts[i_c - 1][0], c_pts[i_c + 1][1] - c_pts[i_c - 1][1]
                        na, nb, nc = math.hypot(ax, ay), math.hypot(bx, by), math.hypot(cx, cy)
                        if na < 1e-6 or nb < 1e-6 or nc < 1e-6:
                            continue
                        cross = ax * by - ay * bx
                        ang = math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb))))
                        total_ang += ang
                        if na + nb >= 2.0:
                            ks.append((2.0 * abs(cross)) / (na * nb * nc))
                        if ang >= math.radians(15.0):
                            sign = 1 if cross > 0 else -1
                            if prev_sign != 0 and sign != prev_sign:
                                reversals += 1
                            prev_sign = sign
                    avg_k = total_ang / max(chunk_len, 1.0)
                    p80_k = sorted(ks)[int(0.80 * (len(ks) - 1))] if ks else avg_k
                    eff_k = max(avg_k, 0.75 * p80_k)
                    s_cap = max(cfg['spline_min_velocity'], d_vel * cfg['spline_vel_scale'])
                    c_vel = s_cap if eff_k <= 1e-6 else min(s_cap, math.sqrt(cfg['spline_max_lateral_acc'] / eff_k))
                    w_rate = reversals / max(chunk_len / 15.0, 1.0)
                    if reversals >= 2 and w_rate > 0.5:
                        c_vel *= max(0.70, 1.0 / (1.0 + 0.18 * w_rate))
                    c_vel = max(cfg['spline_min_velocity'], min(s_cap, c_vel))
                    ratio = c_vel / max(d_vel, 1e-6)
                    c_acc = max(cfg['spline_min_acceleration'], min(d_acc * cfg['spline_vel_scale'], d_acc * (ratio ** 1.35)))
                s_time += _trap_move_sec(chunk_len, c_vel, c_acc)
                prev_pt = chunk[-1]

        # 획 종료 후 공중 이격 상승
        s_time += lift_sec

        running_len += stroke_len
        running_sec += s_time
        cum_length.append(running_len)
        cum_time.append(running_sec)
        prev_end = pts[-1]

    profile = {
        'total_strokes': len(strokes),
        'total_length_mm': round(running_len, 1),
        'pre_cal_sec': round(pre_cal_sec, 1),
        'strokes_total_sec': round(running_sec, 1),
        'finish_sec': round(finish_sec, 1),
        'total_sec': round(pre_cal_sec + running_sec + finish_sec, 1),
        'cum_length_mm': cum_length,
        'cum_stroke_sec': cum_time,
    }
    if len(_PLAN_PROFILE_CACHE) > 8:
        _PLAN_PROFILE_CACHE.clear()
    _PLAN_PROFILE_CACHE[key] = (stat.st_mtime_ns, profile)
    return profile


def _plan_length_progress(plan_path, completed_strokes: int, *, job_id: str = '', robot_state: str = '') -> dict | None:
    """선 길이·이동/상하강·펜 교체 시간을 반영해 진행률(%)과 실시간 보정 예상 남은 시간을 계산합니다."""
    profile = _estimate_plan_profile(plan_path)
    if not profile:
        return None
    cum_len = profile['cum_length_mm']
    cum_sec = profile['cum_stroke_sec']
    total_mm = profile['total_length_mm']
    total_strokes = profile['total_strokes']
    pre_cal = profile['pre_cal_sec']
    strokes_total_sec = profile['strokes_total_sec']
    finish_sec = profile['finish_sec']

    idx = max(0, min(int(completed_strokes), total_strokes))
    done_mm = cum_len[idx - 1] if idx > 0 else 0.0
    done_stroke_sec = cum_sec[idx - 1] if idx > 0 else 0.0

    # 실행 중 실측 속도로 남은 시간 실시간 보정 (일시정지 시간은 제외)
    now = time.monotonic()
    scale = 1.0
    active_since_start = 0.0
    if job_id:
        if len(_JOB_TIMING) > 16:
            _JOB_TIMING.clear()
        rec = _JOB_TIMING.setdefault(job_id, {
            'started_at': None,
            'paused_accum': 0.0,
            'pause_started': None,
            'first_stroke_at': None,
            'first_stroke_id': 0,
            'first_stroke_model_sec': 0.0,
        })
        if robot_state in ('DRAWING', 'DISPATCHING', 'RESUMING'):
            if rec['started_at'] is None:
                rec['started_at'] = now
            if rec['pause_started'] is not None:
                rec['paused_accum'] += max(0.0, now - rec['pause_started'])
                rec['pause_started'] = None
        elif robot_state in ('PAUSING', 'PAUSED', 'FORCE_STOPPED'):
            if rec['started_at'] is not None and rec['pause_started'] is None:
                rec['pause_started'] = now

        if rec['started_at'] is not None:
            paused_now = rec['paused_accum'] + (max(0.0, now - rec['pause_started']) if rec['pause_started'] is not None else 0.0)
            active_since_start = max(0.0, now - rec['started_at'] - paused_now)
            if idx >= 1 and rec['first_stroke_at'] is None:
                rec['first_stroke_at'] = active_since_start
                rec['first_stroke_id'] = idx
                rec['first_stroke_model_sec'] = done_stroke_sec
            elif idx >= rec['first_stroke_id'] + 3 and rec['first_stroke_at'] is not None:
                actual_draw = active_since_start - rec['first_stroke_at']
                model_draw = done_stroke_sec - rec['first_stroke_model_sec']
                if actual_draw >= 3.0 and model_draw >= 2.0:
                    ratio = max(0.55, min(1.85, actual_draw / model_draw))
                    weight = min(0.75, (idx - rec['first_stroke_id']) / 20.0)
                    scale = (1.0 - weight) * 1.0 + weight * ratio

    if robot_state == 'COMPLETED' or idx >= total_strokes:
        pct = 100.0
        rem_sec = 0.0
        est_total_sec = pre_cal + strokes_total_sec * scale + finish_sec
    elif idx == 0:
        est_total_sec = pre_cal + strokes_total_sec + finish_sec
        rem_cal = max(2.0, pre_cal - active_since_start)
        done_cal = min(pre_cal - 2.0, active_since_start)
        rem_sec = rem_cal + strokes_total_sec + finish_sec
        pct = round(min(15.0, (done_cal / est_total_sec) * 100.0), 1) if est_total_sec > 0 else 0.0
    else:
        est_total_sec = pre_cal + strokes_total_sec * scale + finish_sec
        rem_sec = (strokes_total_sec - done_stroke_sec) * scale + finish_sec
        done_sec = pre_cal + done_stroke_sec * scale
        pct = round(min(99.9, max(0.0, (done_sec / est_total_sec) * 100.0)), 1) if est_total_sec > 0 else 0.0

    return {
        'completed_length_mm': round(done_mm, 1),
        'total_length_mm': round(total_mm, 1),
        'progress_percent': pct,
        'estimated_total_sec': round(est_total_sec, 1),
        'estimated_remaining_sec': round(max(0.0, rem_sec), 1),
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
    resp = {
        'job_id': data['job_id'], 'phase': data['phase'], 'ticket': data['ticket'],
        'preview_url': '/api/kiosk/preview', 'text': data['text'],
    }
    if data.get('estimated_total_sec') is not None:
        resp['estimated_total_sec'] = data['estimated_total_sec']
    if data.get('total_strokes') is not None:
        resp['total_strokes'] = data['total_strokes']
    if data.get('total_length_mm') is not None:
        resp['total_length_mm'] = data['total_length_mm']
    return resp


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
    method: str = Form(''),
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
    # 항상 MFL-LD 선화 엔진으로 고정합니다.
    method = 'mfl_ld'
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
        can_reuse = (previous and previous['phase'] == 'PREVIEW'
                     and previous.get('photo_sha256') == photo_hash
                     and previous.get('detail') == detail and previous.get('paper', 'a4') == paper
                     and previous.get('method') == method)
        timing_est = get_prepare_timing_estimate()
        now = time.time()
        data = dict(
            version=1, job_id=job_id, text=text, phase='PREPARING',
            ticket=secrets.token_urlsafe(32), prepare_request_id=request_id,
            input_sha256=fingerprint, photo_sha256=photo_hash, detail=detail, paper=paper, method=method,
            created_at=now, error='',
            prepare_stage='PLAN' if can_reuse else 'LINEART',
            prepare_reused_lineart=bool(can_reuse),
            prepare_started_at=now,
            prepare_stage_started_at=now,
            prepare_est_lineart_sec=timing_est['lineart_sec'],
            prepare_est_plan_sec=timing_est['plan_sec'],
        )
        save_state(data)
        try:
            body = dict(job_id=job_id, method=method,
                        paper=paper, detail=detail)
            if can_reuse:
                # 확정된 옛 계획은 수정하지 않고, 같은 선화로 새 계획을 생성합니다.
                os.link(artifact(previous, 'lineart.png'), directory / 'lineart.png')
                atomic_json(directory / 'job_metadata.json', dict(job_id=job_id, confirmed=False,
                            engine=body['method'], reused_lineart_from=previous['job_id']))
            else:
                t_lineart = time.perf_counter()
                result = await bridge_request(request, 'POST', '/bridge/artwork', body={
                    **body, 'stage': 'LINEART', 'input_path': str(directory / 'photo.png'),
                }, timeout=150.)
                if result.get('job_id') != job_id:
                    raise HTTPException(502, 'Pipeline 작업 ID가 일치하지 않습니다.')
                _record_prepare_timing('lineart_sec', time.perf_counter() - t_lineart)
            artifact(data, 'lineart.png')
            data.update(prepare_stage='PLAN', prepare_stage_started_at=time.time())
            save_state(data)
            metadata_path = directory / 'job_metadata.json'
            metadata = json.loads(metadata_path.read_text())
            # 계획 미리보기와 사용자의 물리 실행 승인은 별개입니다.
            atomic_json(metadata_path, {**metadata, 'preview_requested': True,
                                        'confirmed': False, 'approved': False, 'text': text})
            t_plan = time.perf_counter()
            result = await bridge_request(request, 'POST', '/bridge/artwork', body={
                **body, 'stage': 'PLAN', 'input_path': str(directory / 'lineart.png'), 'text': text,
            }, timeout=150.)
            if result.get('job_id') != job_id:
                raise HTTPException(502, 'Pipeline 작업 ID가 일치하지 않습니다.')
            _record_prepare_timing('plan_sec', time.perf_counter() - t_plan)
            plan = artifact(data, 'drawing_plan.json')
            artifact(data, 'preview.svg')
            summary = load_plan(job_id, str(plan), plan_root=job_root())
            profile = _estimate_plan_profile(plan)
            data.update(
                phase='PREVIEW',
                sha256=summary.sha256,
                prepare_stage='DONE',
                estimated_total_sec=profile['total_sec'] if profile else None,
                total_strokes=profile['total_strokes'] if profile else None,
                total_length_mm=profile['total_length_mm'] if profile else None,
            )
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
    result = {key: data.get(key) for key in ('job_id', 'text', 'phase', 'error', 'estimated_total_sec', 'total_strokes', 'total_length_mm')}
    result.update(status=None, can_prepare=True, prepare_progress=None)
    if data['phase'] == 'PREPARING':
        result['prepare_progress'] = _compute_prepare_progress(data)
    if data['phase'] == 'PREVIEW' and result.get('estimated_total_sec') is None:
        try:
            profile = _estimate_plan_profile(artifact(data, 'drawing_plan.json'))
            if profile:
                result['estimated_total_sec'] = profile['total_sec']
                result['total_strokes'] = profile['total_strokes']
                result['total_length_mm'] = profile['total_length_mm']
        except HTTPException:
            pass
    if data['phase'] in SUBMITTED:
        try:
            status = await observed_status(request, data['job_id'])
            length_info = _plan_length_progress(
                artifact(data, 'drawing_plan.json'),
                status['completed_strokes'],
                job_id=data['job_id'],
                robot_state=status['state'],
            )
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
