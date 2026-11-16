"""터미널 실행 기록(stdout/stderr/ROS2 로그 포함)을 run_logs 폴더에 저장하는 유틸리티.

파일명 형식: <최초 실행시간>_<실행 종료시간>.txt (예: 20261116_184600_20261116_184715.txt)
"""

from datetime import datetime
import os
import sys
import threading
from typing import Optional

DEFAULT_LOG_DIR = "/home/qownsdud/ws_cobot_pjt/ws_dsr/run_logs"


class RunLogSession:
    """OS 레벨 FD(1, 2)를 복제(Tee)해 터미널과 파일에 동시에 기록하는 컨텍스트 매니저."""

    def __init__(self, label: str = "", log_dir: str = DEFAULT_LOG_DIR) -> None:
        self.label = label
        self.log_dir = log_dir
        self.start_dt: Optional[datetime] = None
        self.tmp_path: Optional[str] = None
        self.final_path: Optional[str] = None
        self._orig_stdout_fd: Optional[int] = None
        self._orig_stderr_fd: Optional[int] = None
        self._pipe_r: Optional[int] = None
        self._pipe_w: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._log_file = None

    def __enter__(self) -> "RunLogSession":
        os.makedirs(self.log_dir, exist_ok=True)
        self.start_dt = datetime.now()
        self.tmp_path = os.path.join(
            self.log_dir,
            f".tmp_{self.start_dt.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.txt",
        )
        self._log_file = open(self.tmp_path, "wb")

        sys.stdout.flush()
        sys.stderr.flush()

        self._orig_stdout_fd = os.dup(1)
        self._orig_stderr_fd = os.dup(2)
        self._pipe_r, self._pipe_w = os.pipe()

        os.dup2(self._pipe_w, 1)
        os.dup2(self._pipe_w, 2)
        os.close(self._pipe_w)
        self._pipe_w = None

        self._reader_thread = threading.Thread(target=self._tee_loop, daemon=True)
        self._reader_thread.start()

        if self.label:
            print(f"[RunLog] 시작 ({self.label}): {self.start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        return self

    def _tee_loop(self) -> None:
        assert self._pipe_r is not None
        orig_fd = self._orig_stdout_fd
        log_file = self._log_file
        assert orig_fd is not None and log_file is not None
        while True:
            chunk = os.read(self._pipe_r, 4096)
            if not chunk:
                break
            os.write(orig_fd, chunk)
            log_file.write(chunk)
            log_file.flush()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        end_dt = datetime.now()
        if self.label:
            print(f"[RunLog] 종료 ({self.label}): {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        sys.stdout.flush()
        sys.stderr.flush()

        # FD 1, 2를 원래 터미널 FD로 복원하면 파이프 쓰기 끝이 닫혀 _tee_loop가 EOF를 받고 종료됨
        if self._orig_stdout_fd is not None:
            os.dup2(self._orig_stdout_fd, 1)
        if self._orig_stderr_fd is not None:
            os.dup2(self._orig_stderr_fd, 2)

        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)

        if self._orig_stdout_fd is not None:
            os.close(self._orig_stdout_fd)
            self._orig_stdout_fd = None
        if self._orig_stderr_fd is not None:
            os.close(self._orig_stderr_fd)
            self._orig_stderr_fd = None

        if self._pipe_r is not None:
            os.close(self._pipe_r)
            self._pipe_r = None

        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

        if self.tmp_path and os.path.exists(self.tmp_path) and self.start_dt is not None:
            start_str = self.start_dt.strftime("%Y%m%d_%H%M%S")
            end_str = end_dt.strftime("%Y%m%d_%H%M%S")
            self.final_path = os.path.join(self.log_dir, f"{start_str}_{end_str}.txt")
            os.replace(self.tmp_path, self.final_path)
            print(f"[RunLog] 저장 완료: {self.final_path}")
