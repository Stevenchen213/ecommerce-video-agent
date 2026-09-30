"""蝉镜 Open API 基础客户端：鉴权、统一请求、错误处理、重试、轮询。

接口约定参考蝉镜官方 chan-skills 与开放平台文档：
  - POST /open/v1/access_token  用 app_id + secret_key 换 access_token
  - 其余接口在 header 里带 access_token
  - 返回体为 {"code": 0, "msg": "...", "data": ...}，code != 0 视为失败
字段名如与你们拿到的合作文档不一致，只需改本文件和各业务模块里的 payload，编排层不用动。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import requests

log = logging.getLogger("chanjing")

# 需要刷新 token 后重试的错误码（示例值，按官方错误码表补充）
TOKEN_INVALID_CODES = {10400, 10401}


class ChanjingError(Exception):
    def __init__(self, code: Any, msg: str, path: str = ""):
        super().__init__(f"[{path}] code={code} msg={msg}")
        self.code, self.msg, self.path = code, msg, path


class PollTimeout(ChanjingError):
    pass


class ChanjingClient:
    def __init__(self, app_id: str, secret_key: str, base_url: str,
                 timeout: int = 30, max_retries: int = 3):
        if not app_id or not secret_key:
            raise ValueError("缺少 CHANJING_APP_ID / CHANJING_SECRET_KEY")
        self.app_id, self.secret_key = app_id, secret_key
        self.base_url = base_url.rstrip("/")
        self.timeout, self.max_retries = timeout, max_retries
        self._session = requests.Session()
        self._token: str | None = None
        self._expire_at = 0.0
        self._lock = threading.Lock()   # 多线程提交任务时只刷新一次 token

    # ---------- 鉴权 ----------
    def _refresh_token(self) -> None:
        path = "/open/v1/access_token"
        resp = self._session.post(self.base_url + path, timeout=self.timeout,
                                  json={"app_id": self.app_id, "secret_key": self.secret_key})
        data = self._unwrap(resp, path)
        self._token = data["access_token"]
        exp = float(data.get("expire_in", 3600))
        # expire_in 可能是秒数也可能是时间戳，两种都兼容；提前 5 分钟刷新
        self._expire_at = (exp if exp > 1e9 else time.time() + exp) - 300
        log.info("access_token 已刷新")   # 不打印 token 本身

    def _get_token(self) -> str:
        with self._lock:
            if not self._token or time.time() >= self._expire_at:
                self._refresh_token()
            return self._token  # type: ignore[return-value]

    # ---------- 请求 ----------
    @staticmethod
    def _unwrap(resp: requests.Response, path: str) -> Any:
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 0:
            raise ChanjingError(body.get("code"), body.get("msg", ""), path)
        return body.get("data")

    def request(self, method: str, path: str, **kwargs) -> Any:
        token_retried = False
        for attempt in range(1, self.max_retries + 1):
            headers = {"access_token": self._get_token(), "Content-Type": "application/json"}
            try:
                resp = self._session.request(method, self.base_url + path, headers=headers,
                                             timeout=self.timeout, **kwargs)
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                return self._unwrap(resp, path)
            except ChanjingError as e:
                if e.code in TOKEN_INVALID_CODES and not token_retried:
                    self._token, token_retried = None, True
                    continue
                raise                      # 业务错误不盲目重试
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
                if attempt == self.max_retries:
                    raise
                wait = 2 ** attempt
                log.warning("%s %s 失败(%s)，%ss 后重试", method, path, e, wait)
                time.sleep(wait)

    def get(self, path: str, **params) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict) -> Any:
        return self.request("POST", path, json=body)

    # ---------- 通用轮询 ----------
    @staticmethod
    def poll(fetch: Callable[[], dict], is_done: Callable[[dict], bool],
             is_failed: Callable[[dict], bool], interval: int, timeout: int,
             label: str = "") -> dict:
        start = time.time()
        while True:
            state = fetch()
            if is_done(state):
                return state
            if is_failed(state):
                raise ChanjingError(state.get("status"),
                                    str(state.get("msg") or state.get("err_msg") or ""), label)
            if time.time() - start > timeout:
                raise PollTimeout("timeout", f"轮询超过 {timeout}s", label)
            time.sleep(interval)
