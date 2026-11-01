"""Demo-only API on 8001. Does not import app settings, read .env, or load keys."""

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from demo_autonomy.engine import Engine, HumanRequiredError, Settings, SimulatedAdapter


class Mandate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supplier: str
    recipient: str
    payment_cap: int = Field(gt=0, le=10**15)
    funding_cap: int = Field(gt=0, le=10**15)


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal: str = Field(min_length=1, max_length=500)
    request_key: str = Field(min_length=8, max_length=100)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    payment_cap: int = Field(ge=0, le=10**15)
    funding_cap: int = Field(ge=0, le=10**15)


def create_demo(settings: Settings, admin_token: str, agent_token: str):
    if len(admin_token) < 32 or len(agent_token) < 32 or admin_token == agent_token:
        raise ValueError("Independent demo credentials required")
    engine = Engine(settings)

    def admin(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + admin_token):
            raise HTTPException(403, "ADMIN_REQUIRED")

    def agent(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, "Bearer " + agent_token):
            raise HTTPException(403, "AGENT_REQUIRED")

    def enabled():
        if not settings.enabled:
            raise HTTPException(503, "AUTONOMY_DISABLED")

    async def worker():
        adapter = SimulatedAdapter(engine)
        while True:
            with engine.db() as db:
                rows = db.execute(
                    "SELECT id,state FROM tasks WHERE state IN ('PLANNING','READY')"
                ).fetchall()
            for row in rows:
                try:
                    if row["state"] == "PLANNING":
                        await engine.plan(row["id"])
                    else:
                        await engine.tick(row["id"], adapter)
                except Exception:
                    engine.hold(row["id"], "WORKER_FAILURE")
            await asyncio.sleep(0.25)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if settings.enabled:
            engine.initialize()
            task = asyncio.create_task(worker())
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="KiteShield Gate 1 — SIMULATED", lifespan=lifespan)
    app.state.engine = engine

    @app.get("/health")
    def health():
        return {
            "profile": "isolated-demo",
            "mode": "SIMULATED",
            "enabled": settings.enabled,
            "planner_enabled": settings.planner_enabled,
            "signing": False,
        }

    @app.put("/mandate", dependencies=[Depends(enabled), Depends(admin)])
    def mandate(payload: Mandate):
        try:
            engine.configure(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"mode": "SIMULATED", "saved": True}

    @app.post("/goals", dependencies=[Depends(enabled), Depends(agent)])
    def goal(payload: Goal):
        try:
            task_id = engine.create(**payload.model_dump())
        except (ValueError, HumanRequiredError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"task_id": task_id, "mode": "SIMULATED"}

    @app.get("/goals/{task_id}", dependencies=[Depends(enabled), Depends(agent)])
    def get(task_id: str):
        try:
            return engine.get(task_id)
        except KeyError as exc:
            raise HTTPException(404, "TASK_NOT_FOUND") from exc

    @app.post("/goals/{task_id}/tighten", dependencies=[Depends(enabled), Depends(agent)])
    def tighten(task_id: str, payload: Limits):
        try:
            engine.tighten(task_id, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, "TASK_NOT_FOUND") from exc
        return {"tightened": True}

    return app
