"""Seedance 图生视频客户端（火山方舟 Ark）— 产品镜头的「素材库没有」兜底。

接口：
  POST {base}/contents/generations/tasks        创建任务 → {"id": "cgt-..."}
  GET  {base}/contents/generations/tasks/{id}   轮询 → status: queued/running/succeeded/failed
  成功后 content.video_url 是 MP4 临时链接（约 24 小时失效，必须立刻下载）

图片输入（三选一，自动识别）：
  - 公网 URL：https://...（TOS 等对象存储）
  - data URL：data:image/png;base64,...
  - 本地路径：自动转成 base64 data URL —— 本地联调不需要先传 TOS

参数写法有两种（不同模型版本支持不同）：
  - 顶层字段：ratio / duration / watermark（较新的模型）
  - 写在提示词末尾：--ratio 9:16 --duration 5 --watermark false（老模型）
  用 SEEDANCE_PARAMS_IN_TEXT=1 切换。报参数错误时先试试切换这个开关。

这里用 requests 直接调 HTTP，不依赖 volcengine 的 arkruntime SDK，
写法与 feiying.py 保持一致，方便大家对照维护。
"""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any

import requests

DEFAULT_ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"


class SeedanceError(RuntimeError):
    pass


class SeedanceBudgetExceeded(SeedanceError):
    """本次运行调用次数超过上限（防止脚本写错导致批量烧钱）。"""


class SeedanceClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "",
        *,
        ratio: str = "9:16",
        resolution: str = "",
        watermark: bool = False,
        allowed_durations: tuple[int, ...] = (5, 10),
        params_in_text: bool = False,
        max_calls: int = 3,
        poll_interval_sec: float = 10.0,
        poll_timeout_sec: float = 900.0,
        download_timeout_sec: float = 300.0,
        session: requests.Session | None = None,
    ):
        if not api_key:
            raise ValueError("缺少 ARK_API_KEY")
        if not model:
            raise ValueError("缺少 SEEDANCE_MODEL（填火山方舟控制台里的模型 ID / 接入点 ID）")
        self.api_key = api_key
        self.model = model
        self.base_url = (base_url or DEFAULT_ARK_BASE).rstrip("/")
        self.ratio = ratio
        self.resolution = resolution
        self.watermark = watermark
        self.allowed_durations = tuple(sorted(allowed_durations)) or (5,)
        self.params_in_text = params_in_text
        self.max_calls = max_calls
        self.calls_made = 0
        self.poll_interval_sec = poll_interval_sec
        self.poll_timeout_sec = poll_timeout_sec
        self.download_timeout_sec = download_timeout_sec
        self._http = session or requests.Session()

    # ---------- 工具 ----------

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def pick_duration(self, need_sec: float | None) -> int:
        """Seedance 只能出固定档位时长：取 ≥ 需要时长的最小档，之后本地裁剪。"""
        if not need_sec or need_sec <= 0:
            return self.allowed_durations[0]
        for d in self.allowed_durations:
            if d >= need_sec:
                return d
        return self.allowed_durations[-1]

    @staticmethod
    def image_to_url(image: str | Path) -> str:
        s = str(image)
        if s.startswith(("http://", "https://", "data:")):
            return s
        p = Path(s)
        if not p.exists():
            raise FileNotFoundError(f"产品图不存在: {p}")
        mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def _check(self, resp: requests.Response, context: str) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text[:500]}
        if resp.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            msg = (err or {}).get("message") if isinstance(err, dict) else None
            raise SeedanceError(f"Seedance HTTP {resp.status_code} {context}: {msg or data}")
        return data

    # ---------- 三步：创建 / 轮询 / 下载 ----------

    def create_task(self, prompt: str, image: str | Path | None = None, duration: int = 5) -> str:
        if self.calls_made >= self.max_calls:
            raise SeedanceBudgetExceeded(
                f"本次运行 Seedance 已调用 {self.calls_made} 次，达到上限 {self.max_calls}。"
                f"确认没写错脚本后，调大 SEEDANCE_MAX_CALLS_PER_RUN 再跑。"
            )
        text = prompt.strip() or "产品展示镜头，画面干净，光线明亮"
        if self.params_in_text:
            text += f" --ratio {self.ratio} --duration {duration} --watermark {str(self.watermark).lower()}"
            if self.resolution:
                text += f" --resolution {self.resolution}"
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if image:
            content.append({"type": "image_url", "image_url": {"url": self.image_to_url(image)}})

        body: dict[str, Any] = {"model": self.model, "content": content}
        if not self.params_in_text:
            body.update({"ratio": self.ratio, "duration": duration, "watermark": self.watermark})
            if self.resolution:
                body["resolution"] = self.resolution

        resp = self._http.post(
            f"{self.base_url}/contents/generations/tasks",
            headers=self._headers, json=body, timeout=60,
        )
        data = self._check(resp, "create_task")
        task_id = data.get("id")
        if not task_id:
            raise SeedanceError(f"创建任务响应缺少 id: {data}")
        self.calls_made += 1
        return task_id

    def wait(self, task_id: str) -> str:
        deadline = time.monotonic() + self.poll_timeout_sec
        while True:
            resp = self._http.get(
                f"{self.base_url}/contents/generations/tasks/{task_id}",
                headers=self._headers, timeout=30,
            )
            data = self._check(resp, f"get_task {task_id}")
            status = data.get("status")
            if status == "succeeded":
                url = (data.get("content") or {}).get("video_url")
                if not url:
                    raise SeedanceError(f"任务成功但没有 video_url: {data}")
                return url
            if status in {"failed", "cancelled", "expired"}:
                raise SeedanceError(f"Seedance 任务 {task_id} {status}: {data.get('error')}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"Seedance 任务 {task_id} 超过 {self.poll_timeout_sec:.0f}s 未完成")
            time.sleep(self.poll_interval_sec)

    def download(self, url: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = output_path.with_suffix(output_path.suffix + ".part")
        with self._http.get(url, stream=True, timeout=(15, self.download_timeout_sec)) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        tmp.replace(output_path)
        return output_path

    def generate(
        self,
        prompt: str,
        output_path: Path,
        *,
        image: str | Path | None = None,
        need_sec: float | None = None,
    ) -> dict[str, Any]:
        duration = self.pick_duration(need_sec)
        task_id = self.create_task(prompt, image=image, duration=duration)
        print(f"  [Seedance] 任务 {task_id} 已提交（{duration}s），等待生成…", flush=True)
        url = self.wait(task_id)
        self.download(url, output_path)
        return {"task_id": task_id, "duration": duration, "video_url": url}
