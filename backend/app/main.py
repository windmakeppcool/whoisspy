"""uvicorn 入口：python -m app.main 或 uvicorn app.main:app。"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn

from app.api.app import create_app

app = create_app()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="whoisspy 后端")
    parser.add_argument("--tui", action="store_true", help="启动 TUI 观看器")
    parser.add_argument("--match-id", type=int, default=1, help="TUI 观看的对局 ID")
    parser.add_argument("--port", type=int, default=8000, help="后端端口")
    return parser.parse_args(argv)


async def start_backend(port: int) -> None:
    """在后台启动后端服务。"""
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def run_tui_mode(match_id: int, port: int) -> None:
    """TUI 模式：启动后端 + 打开 TUI。"""
    # 在后台启动后端
    backend_task = asyncio.create_task(start_backend(port))

    # 等待后端启动
    await asyncio.sleep(1.0)

    # 启动 TUI
    from app.tui.main import run_tui
    try:
        await run_tui(base_url=f"http://127.0.0.1:{port}", match_id=match_id)
    finally:
        backend_task.cancel()


if __name__ == "__main__":
    args = parse_args()

    if args.tui:
        # TUI 模式
        asyncio.run(run_tui_mode(args.match_id, args.port))
    else:
        # 正常模式
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
