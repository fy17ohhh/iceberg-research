from __future__ import annotations

import json
import logging
import os
import asyncio
import shutil
import subprocess
import time
import threading
from concurrent.futures import Future

from typing import Any
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession

logger = logging.getLogger(__name__)


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str]
    env: dict[str, str] | None = None
    required: bool = False

    def to_stdio_params(self) -> StdioServerParameters:
        env = {**os.environ, **self.env} if self.env else os.environ
        config = StdioServerParameters(
            command=self.command, 
            args=self.args, 
            env=env,
        )
        return config


class MCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.name = config.name
        self.server_config: StdioServerParameters = config.to_stdio_params()
        self._thread = None
        self._queue = None
        self._ready_event = None
        self._loop = None
        self._connect_error = None
        self.tools = []

    def connect(self) -> list[Tool]:
        self._queue = asyncio.Queue()

        self._ready_event = threading.Event()
        self._thread = threading.Thread(target=self._run_background, daemon=True)
        self._thread.start()

        self._ready_event.wait()

        if self._connect_error:
            raise self._connect_error

        logger.info("[MCP] Connected: %s (%d tools)", self.name, len(self.tools))
        return self.tools

    def _run_background(self):
        asyncio.run(self._async_main())

    async def _async_main(self):
        self._loop = asyncio.get_running_loop()

        try:
            async with stdio_client(self.server_config) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.tools = (await session.list_tools()).tools
                    # (
                    #     self._session.list_tools(),
                    #     await self._session.list_resources(),
                    #     await self._session.list_prompts(),
                    # )
                    self._connect_error = None
                    self._ready_event.set()

                    while True:
                        command = await self._queue.get()
                        if command is None:
                            break

                        future: Future
                        name, args, future = command
                        try:
                            result = await session.call_tool(name=name, arguments=args)
                            future.set_result(result)
                        except Exception as e:
                            future.set_exception(e)
        except Exception as e:
            self._connect_error = e
            self._ready_event.set()

    def call_tool(self, name: str, args: dict[str, Any], _max_retries: int = 3):
        from ..tools.base_tool import ToolCallError

        if self._loop is None:
            raise RuntimeError("MCPClient is not connected")

        for attempt in range(_max_retries + 1):
            future = Future()
            self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, args, future))
            try:
                result: CallToolResult = future.result()
            except Exception as e:
                if "already borrowed" in str(e).lower() and attempt < _max_retries:
                    logger.warning("[MCP] %s: already borrowed, retry %d/%d", name, attempt + 1, _max_retries)
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ToolCallError.from_exception(e, tool_name=name) from e

            if result.isError:
                error_text = result.content[0].text if result.content else "Unknown error"
                if "already borrowed" in error_text.lower() and attempt < _max_retries:
                    logger.warning("[MCP] %s: already borrowed, retry %d/%d", name, attempt + 1, _max_retries)
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ToolCallError(message=f"Tool call failed: {error_text}", tool_name=name)

            return "\n".join(item.text for item in result.content)

        raise ToolCallError(message="Tool call failed: already borrowed retry limit reached", tool_name=name)

    def disconnect(self):
        if self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        self._thread.join()
        self._loop = None


def create_mcp_clients(json_path: str) -> list[MCPClient]:
    with open(json_path, "r", encoding="utf-8") as f:
        configs: dict[str, dict] = json.load(f)

    server_configs: list[MCPServerConfig] = []
    for name, config in configs.items():
        env: dict[str, str] = config.get("env")
        if env:
            for key, value in env.items():
                if value.startswith("${") and value.endswith("}"):
                    env[key] = os.getenv(value[2:-1], "")

        command = config["command"]
        args = config["args"]
        if name == "medium-reader" and not _medium_reader_ready(command):
            logger.info(
                "[MCP] Skipping Medium Reader: ZMediumToMarkdown is not ready; "
                "install the gem and run `mcp-medium-reader init` to enable it"
            )
            continue
        if name == "github":
            github_token = (env or {}).get("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
            if not github_token:
                logger.info("[MCP] Skipping GitHub: GITHUB_TOKEN is not configured")
                continue

            native_binary = shutil.which("github-mcp-server")
            if native_binary:
                command = native_binary
                args = ["stdio"]
                logger.info("[MCP] GitHub will use the native MCP server")
            elif not _docker_daemon_available():
                logger.info(
                    "[MCP] Skipping GitHub: Docker daemon is not running and "
                    "the native github-mcp-server binary is not installed"
                )
                continue

        server_config = MCPServerConfig(
            name=name,
            command=command,
            args=args,
            env=env,
            required=config.get("required", False),
        )
        server_configs.append(server_config)

    clients = []
    for config in server_configs:
        client = MCPClient(config)
        try:
            client.connect()
        except Exception as exc:
            if config.required:
                raise RuntimeError(
                    f"Required MCP server '{config.name}' failed to initialize"
                ) from exc
            logger.warning(
                "[MCP] Optional server '%s' is unavailable and will be skipped: %s",
                config.name,
                exc,
            )
            continue
        clients.append(client)

    return clients


def _docker_daemon_available() -> bool:
    """Return whether Docker commands can reach a running daemon."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _medium_reader_ready(command: str) -> bool:
    """Check Medium Reader's Ruby dependency without starting its MCP server."""
    if shutil.which(command) is None:
        return False
    try:
        result = subprocess.run(
            [command, "doctor"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "ZMediumToMarkdown:\n  ERROR:" not in result.stdout
