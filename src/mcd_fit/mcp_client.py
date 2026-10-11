"""极简 MCP (Model Context Protocol) 客户端 —— Streamable HTTP 传输。

仅依赖 Python 标准库，便于脱离 WorkBuddy 独立运行与单元测试。
协议要点：
- JSON-RPC 2.0 over HTTP；``Accept: application/json, text/event-stream``；
- 服务端可能返回 ``Mcp-Session-Id``，后续请求原样回传；
- 响应体可能是 JSON，也可能是 SSE，两种都要能解析。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "mcd-fit-buddy"
CLIENT_VERSION = "1.0.0"


class McpError(RuntimeError):
    """MCP 调用失败。"""


class McpClient:
    def __init__(self, url: str, token: str = "", timeout: float = 30.0) -> None:
        if not url:
            raise ValueError("MCP 服务地址不能为空")
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._next_id = 1

    # ------------------------------------------------------------------ #
    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise McpError(f"HTTP {e.code} 调用 MCP 失败: {detail[:500]}") from e
        except urllib.error.URLError as e:
            raise McpError(f"网络错误: {e.reason}") from e
        if not raw.strip():
            return None
        return self._parse(raw, ctype)

    @staticmethod
    def _parse(raw: str, ctype: str) -> Optional[Dict[str, Any]]:
        if "text/event-stream" in ctype or raw.lstrip().startswith("event:"):
            data_lines = [ln.strip()[len("data:"):].strip()
                          for ln in raw.splitlines() if ln.strip().startswith("data:")]
            if not data_lines:
                return None
            raw = "\n".join(data_lines)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise McpError(f"无法解析 MCP 响应: {raw[:500]}") from e

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        msg_id = self._next_id
        self._next_id += 1
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self._post(payload)
        if resp is None:
            raise McpError(f"{method} 未返回响应")
        if "error" in resp:
            raise McpError(f"{method} 返回错误: {resp['error']}")
        return resp.get("result", {})

    def _notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    # ------------------------------------------------------------------ #
    def initialize(self) -> Dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        )
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> List[Dict[str, Any]]:
        return self._rpc("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise McpError(f"Tool {name} 执行失败: {result}")
        content = result.get("content") or []
        if not content:
            return None
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else None
        if text is None:
            return result
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    def close(self) -> None:
        if not self.session_id:
            return
        req = urllib.request.Request(self.url, headers=self._headers(), method="DELETE")
        try:
            urllib.request.urlopen(req, timeout=self.timeout).close()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self.session_id = None
