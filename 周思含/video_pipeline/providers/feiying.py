"""飞影数字人 Provider — 真实 API 实现。

接口文档：https://api.hifly.cc/hifly.html
流程：create_by_tts 提交任务 → 轮询 video/task → 下载临时成片地址。

约定：
- shot.person_id / shot.voice_id 优先；缺省回落到构造参数 / 环境变量
  DEFAULT_PERSON_ID / DEFAULT_VOICE_ID。
- 字幕不在此烧入（st_show=0），由拼接层统一添加。
- shot.extra 可用键（可选）：
    st_show: int            覆盖默认 0
    video_start_msec: int   从数字人源视频指定毫秒开始驱动
    title: str              作品标题（默认用 shot.id）
    poll_timeout_sec: int   覆盖轮询超时
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

from video_pipeline.providers.base import GenerateResult, NotConfiguredProvider, VideoProvider
from video_pipeline.schema import Shot

DEFAULT_API_BASE = "https://hfw-api.hifly.cc"

# 业务错误码（code != 0 时抛出）
_ERROR_HINTS = {
    11: "参数不正确",
    14: "资源不存在",
    1001: "生成中作品数达上限（并发限制，稍后重试）",
    1002: "积分不足",
    1005: "需要开通会员",
    1006: "会员等级不够",
    1009: "高保真声音已售罄",
    1015: "提交作品数达上限",
    2003: "无效 Token",
}


class FeiyingAPIError(RuntimeError):
    """飞影业务错误（带错误码）。"""

    def __init__(self, code: int | None, message: str, context: str = ""):
        self.code = code
        hint = _ERROR_HINTS.get(code, "")
        suffix = f"（{hint}）" if hint else ""
        super().__init__(f"飞影 API 错误 code={code} {message}{suffix} {context}".strip())


class FeiyingProvider(VideoProvider):
    """飞影数字人真实 API。"""

    name = "feiying"

    def __init__(
        self,
        api_base: str = "",
        api_key: str = "",
        *,
        default_person_id: str = "",
        default_voice_id: str = "",
        poll_interval_sec: float = 8.0,
        poll_timeout_sec: float = 600.0,
        download_timeout_sec: float = 300.0,
        session: requests.Session | None = None,
    ):
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.api_key = api_key
        self.default_person_id = default_person_id or os.getenv("DEFAULT_PERSON_ID", "")
        self.default_voice_id = default_voice_id or os.getenv("DEFAULT_VOICE_ID", "")
        self.poll_interval_sec = poll_interval_sec
        self.poll_timeout_sec = poll_timeout_sec
        self.download_timeout_sec = download_timeout_sec
        self._http = session or requests.Session()

    # ---------- 内部 ----------

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _check(self, resp: requests.Response, context: str) -> dict[str, Any]:
        if resp.status_code == 401:
            raise FeiyingAPIError(2003, "HTTP 401，Token 无效或未认证", context)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", 0)
        if code not in (0, None):
            raise FeiyingAPIError(code, data.get("message", ""), context)
        return data

    def _create_task(self, shot: Shot) -> str:
        avatar = shot.person_id or self.default_person_id
        voice = shot.voice_id or self.default_voice_id
        if not avatar:
            raise ValueError(f"shot={shot.id} 缺少 person_id（且未配置默认数字人）")
        if not voice:
            raise ValueError(f"shot={shot.id} 缺少 voice_id（且未配置默认声音）")
        if not shot.text.strip():
            raise ValueError(f"shot={shot.id} 缺少口播文案 text")

        payload: dict[str, Any] = {
            "avatar": avatar,
            "voice": voice,
            "text": shot.text,
            "title": shot.extra.get("title") or shot.id,
            "st_show": int(shot.extra.get("st_show", 0)),
        }
        if "video_start_msec" in shot.extra:
            payload["video_start_msec"] = int(shot.extra["video_start_msec"])

        resp = self._http.post(
            f"{self.api_base}/api/v2/hifly/video/create_by_tts",
            headers=self._headers,
            json=payload,
            timeout=30,
        )
        data = self._check(resp, f"create_by_tts shot={shot.id}")
        task_id = data.get("task_id")
        if not task_id:
            raise FeiyingAPIError(None, f"响应缺少 task_id: {data}", f"shot={shot.id}")
        return task_id

    def _poll_task(self, task_id: str, timeout_sec: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_sec
        while True:
            resp = self._http.get(
                f"{self.api_base}/api/v2/hifly/video/task",
                headers=self._headers,
                params={"task_id": task_id},
                timeout=30,
            )
            data = self._check(resp, f"poll task={task_id}")
            status = data.get("status")
            if status == 3:
                if not data.get("video_Url"):
                    raise FeiyingAPIError(None, "任务完成但缺少 video_Url", task_id)
                return data
            if status == 4:
                raise FeiyingAPIError(
                    None, f"生成失败: {data.get('message', '未知原因')}", task_id
                )
            if time.monotonic() > deadline:
                raise TimeoutError(f"飞影任务 {task_id} 超过 {timeout_sec:.0f}s 未完成")
            time.sleep(self.poll_interval_sec)

    def _download(self, url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._http.get(
            url, stream=True, timeout=(15, self.download_timeout_sec)
        ) as resp:
            resp.raise_for_status()
            tmp = output_path.with_suffix(output_path.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
            tmp.replace(output_path)

    # ---------- 接口 ----------

    def generate_audio(
        self,
        text: str,
        output_path: Path,
        voice_id: str = "",
        title: str = "",
    ) -> Path:
        """纯音频 TTS（audio/create_by_tts）。

        用途：B-roll/产品特写等非数字人镜头的旁白。与数字人镜头传同一个
        克隆声音 ID，即可保证整条视频声音一致。
        """
        if not self.api_key:
            raise RuntimeError("feiying 未配置 API Key，无法生成音频")
        voice = voice_id or self.default_voice_id
        if not voice:
            raise ValueError("缺少 voice_id（且未配置默认声音 DEFAULT_VOICE_ID）")
        if not text.strip():
            raise ValueError("缺少旁白文案 text")

        resp = self._http.post(
            f"{self.api_base}/api/v2/hifly/audio/create_by_tts",
            headers=self._headers,
            json={"voice": voice, "text": text, "title": title or "旁白"},
            timeout=30,
        )
        data = self._check(resp, "audio/create_by_tts")
        task_id = data.get("task_id")
        if not task_id:
            raise FeiyingAPIError(None, f"响应缺少 task_id: {data}", "audio/create_by_tts")

        done = self._poll_task(task_id, self.poll_timeout_sec)
        audio_url = (
            done.get("audio_Url") or done.get("audio_url") or done.get("video_Url")
        )
        if not audio_url:
            raise FeiyingAPIError(None, f"音频任务完成但缺少成片地址: {done}", task_id)
        self._download(audio_url, output_path)
        return output_path

    def generate(self, shot: Shot, output_path: Path) -> GenerateResult:
        if not self.api_key:
            # 与旧占位行为一致：未配置时显式失败
            return NotConfiguredProvider("feiying").generate(shot, output_path)

        task_id = self._create_task(shot)
        timeout = float(shot.extra.get("poll_timeout_sec", self.poll_timeout_sec))
        done = self._poll_task(task_id, timeout)
        self._download(done["video_Url"], output_path)

        return GenerateResult(
            provider=self.name,
            shot_id=shot.id,
            local_path=output_path,
            duration_sec=done.get("duration"),
            width=None,  # 由拼接层 normalize 统一规格
            height=None,
            task_id=task_id,
            raw={
                "mock": False,
                "text": shot.text,
                "avatar": shot.person_id or self.default_person_id,
                "voice": shot.voice_id or self.default_voice_id,
                "video_url": done.get("video_Url"),
            },
        )
