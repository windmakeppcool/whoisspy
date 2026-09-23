"""uvicorn 入口：python -m app.main 或 uvicorn app.main:app。"""

from __future__ import annotations

import uvicorn

from app.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
