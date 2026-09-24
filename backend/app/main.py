"""uvicorn 入口：python -m app.main 或 uvicorn app.main:app。"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn

from app.api.app import create_app
from app.games.registry import PRESETS

app = create_app()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="whoisspy 后端")
    parser.add_argument("--tui", action="store_true", help="启动 TUI 观看器")
    parser.add_argument("--match-id", type=int, default=0,
                        help="TUI 观看的对局 ID（0 = 启动时自动创建一局）")
    parser.add_argument("--real", action="store_true",
                        help="TUI 自动开局用真实 LLM（首个非 mock provider）而非 mock")
    parser.add_argument("--board", default="p6-classic", choices=sorted(PRESETS),
                        help="自动开局的板子（默认 p6-classic）")
    parser.add_argument("--port", type=int, default=8000, help="后端端口")
    return parser.parse_args(argv)


async def create_match_via_api(base_url: str, *, real: bool = False,
                               data_dir: str | None = None,
                               board_id: str = "p6-classic") -> int:
    """通过后端 API 自动创建一局，返回对局 ID。

    座位数按板子 player_count 构建（如 p9-standard = 9 座）。
    real=False 全 mock；real=True 用 providers.json 首个非 mock provider。
    """
    import httpx

    from app.config.loader import load_config, load_env_file
    from app.games.registry import resolve_board

    _, spec = resolve_board({"id": board_id})
    n_players = spec.player_count

    if real:
        load_env_file()  # 先注入 .env，保证后端进程内 key 可解析
        bundle = load_config(data_dir)
        from app.scripts_helpers.e2e import build_real_seats, pick_provider

        provider, model = pick_provider(bundle.providers)
        import os

        env = {**os.environ}
        seats, assignments = build_real_seats(
            provider, model, n_players=n_players, env=env,
            personas=bundle.personas, providers=bundle.providers)
        print("模型分配：")
        for a in assignments:
            print(f"  {a['seat']}号 {a['persona_id']} -> {a['model']} ({a['basis']})")
    else:
        assignments = None
        from app.config.defaults import DEFAULT_PERSONAS

        seats = [{"seat": i,
                  "persona_id": DEFAULT_PERSONAS[(i - 1) % len(DEFAULT_PERSONAS)]["id"],
                  "model": "mock"}
                 for i in range(1, n_players + 1)]
    async with httpx.AsyncClient() as client:
        board: dict = {"id": board_id}
        if assignments:
            board["model_assignments"] = assignments  # 分配记录随 board 落库（D19）
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/matches",
            json={"game_type": "werewolf", "board": board, "seats": seats})
        resp.raise_for_status()
        return int(resp.json()["id"])


async def start_backend(port: int) -> None:
    """在后台启动后端服务。"""
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def run_tui_mode(match_id: int, port: int, *, real: bool = False,
                       board: str = "p6-classic") -> None:
    """TUI 模式：启动后端 + 打开 TUI。match_id 为 0 时自动创建一局。"""
    # 在后台启动后端
    backend_task = asyncio.create_task(start_backend(port))

    # 等待后端启动
    await asyncio.sleep(1.0)

    base_url = f"http://127.0.0.1:{port}"
    if match_id == 0:
        # 自动开局：POST 一局（real 决定 mock 或真实 LLM），用新对局 ID 进入观看
        match_id = await create_match_via_api(base_url, real=real, board_id=board)

    # 启动 TUI
    from app.tui.main import run_tui
    try:
        await run_tui(base_url=base_url, match_id=match_id)
    finally:
        backend_task.cancel()
        try:
            await backend_task
        except asyncio.CancelledError:
            pass  # uvicorn lifespan 在 task-cancel 路径会打印 CancelledError 噪音，正常退出无需关注


if __name__ == "__main__":
    args = parse_args()

    if args.tui:
        # TUI 模式
        asyncio.run(run_tui_mode(args.match_id, args.port, real=args.real,
                                 board=args.board))
    else:
        # 正常模式
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
