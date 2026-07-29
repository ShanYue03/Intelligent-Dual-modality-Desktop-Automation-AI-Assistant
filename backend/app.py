"""FastAPI application — localhost only."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .orchestrator import orchestrator


app = FastAPI(title="Multimodal Assistant API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    orchestrator.set_event_loop(asyncio.get_running_loop())


class VoiceStartBody(BaseModel):
    language: str = Field("EN", description="EN or CN")
    duration: int = Field(5, ge=1, le=30)


class DominantHandBody(BaseModel):
    hand: str = Field("right", description="left or right")


class UserNameBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def status() -> dict:
    return orchestrator.get_status()


@app.get("/api/dashboard")
async def dashboard() -> dict:
    return orchestrator.get_dashboard_data()


@app.get("/api/user")
async def get_user() -> dict[str, str]:
    from user_store import get_current_user_name

    return {"name": get_current_user_name()}


@app.post("/api/user")
async def set_user(body: UserNameBody) -> dict[str, str]:
    from user_store import save_user_name

    name = save_user_name(body.name)
    return {"name": name}


@app.get("/api/voice/chat-history")
async def voice_chat_history() -> dict:
    from .voice_chat_history import load_voice_chat_history

    return {"messages": load_voice_chat_history(days=3)}


@app.post("/api/voice/start")
async def voice_start(body: VoiceStartBody) -> dict:
    return await orchestrator.run_voice_session(body.language, body.duration)


@app.post("/api/gesture/start")
async def gesture_start() -> dict:
    return await orchestrator.start_gesture()


@app.post("/api/gesture/stop")
async def gesture_stop() -> dict:
    return await orchestrator.stop_gesture()


@app.post("/api/gesture/dominant-hand")
async def gesture_dominant_hand(body: DominantHandBody) -> dict:
    return orchestrator.set_dominant_hand(body.hand)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    preview = ws.query_params.get("preview") == "1"
    await ws.accept()
    orchestrator.register_ws(ws, preview=preview)
    try:
        await ws.send_json({"event": "connected", "data": orchestrator.get_status()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        orchestrator.unregister_ws(ws)


def create_app() -> FastAPI:
    return app
