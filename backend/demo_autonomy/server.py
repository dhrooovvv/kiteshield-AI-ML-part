"""Demo-only API on 8001. Does not import app settings, read .env, or load keys."""

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from demo_autonomy.engine import Engine, HumanRequiredError, Settings, SimulatedAdapter


class Mandate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    supplier: str
    recipient: str
    payment_cap: int = Field(gt=0, le=10**15)
    funding_cap: int = Field(ge=0, le=10**18)
    approval_threshold: int = Field(default=1, ge=1, le=10**24)

    @field_validator("funding_cap", "approval_threshold", mode="before")
    @classmethod
    def decimal_budget(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        return value


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    goal: str = Field(min_length=1, max_length=500)
    request_key: str = Field(min_length=8, max_length=100)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    payment_cap: int = Field(ge=0, le=10**15)
    funding_cap: int = Field(ge=0, le=10**18)

    _decimal_budget = field_validator("funding_cap", mode="before")(Mandate.decimal_budget.__func__)


def create_demo(
    settings: Settings,
    admin_token: str,
    agent_token: str,
    approver_token: str = "",
    core_app=None,
    *,
    engine_factory=None,
    adapter_factory=None,
):
    from demo_autonomy.workflows import WorkflowEngine

    if settings.workflows_enabled and not settings.wallet_services_enabled:
        raise ValueError("Workflow demo requires the existing-wallet-services adapter")
    if settings.wallet_services_enabled and not settings.workflows_enabled:
        raise ValueError("Wallet services require workflow enforcement")
    if settings.workflows_enabled and (
        len(approver_token) < (16 if core_app is not None else 32)
        or approver_token in {admin_token, agent_token}
    ):
        raise ValueError("Independent human approver credential required")
    if (
        len(admin_token) < (16 if core_app is not None else 32)
        or len(agent_token) < (16 if core_app is not None else 32)
        or admin_token == agent_token
    ):
        raise ValueError("Independent demo credentials required")
    if settings.mode == "SEPOLIA" and (engine_factory is None or adapter_factory is None):
        raise ValueError("Sepolia requires the separately guarded profile and adapter")
    engine = (
        engine_factory(settings)
        if engine_factory
        else WorkflowEngine(settings)
        if settings.workflows_enabled
        else Engine(settings)
    )

    def credential(authorization, x_api_key):
        return "Bearer " + x_api_key if core_app is not None else authorization

    def admin(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        if not secrets.compare_digest(
            credential(authorization, x_api_key), "Bearer " + admin_token
        ):
            raise HTTPException(403, "ADMIN_REQUIRED")

    def agent(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        if not secrets.compare_digest(
            credential(authorization, x_api_key), "Bearer " + agent_token
        ):
            raise HTTPException(403, "AGENT_REQUIRED")

    def enabled():
        if not settings.enabled:
            raise HTTPException(503, "AUTONOMY_DISABLED")

    def approver(authorization: str = Header(default=""), x_api_key: str = Header(default="")):
        if not approver_token or not secrets.compare_digest(
            credential(authorization, x_api_key), "Bearer " + approver_token
        ):
            raise HTTPException(403, "HUMAN_APPROVER_REQUIRED")

    async def worker(adapter):
        async def advance(row):
            try:
                if row["state"] == "PLANNING":
                    await engine.plan(row["id"])
                else:
                    await engine.tick(row["id"], adapter)
            except Exception:
                engine.hold(row["id"], "WORKER_FAILURE")

        while True:
            with engine.db() as db:
                rows = db.execute(
                    "SELECT id,state FROM tasks "
                    "WHERE state IN ('PLANNING','READY','WAITING_APPROVAL')"
                ).fetchall()
            # Planning is bounded; tasks waiting for approval never stall other tasks.
            await asyncio.gather(*(advance(row) for row in rows))
            await asyncio.sleep(0.5)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if settings.enabled:
            engine.initialize()
            if settings.wallet_services_enabled:
                from demo_autonomy.sandbox import WalletServicesAdapter

                adapter = (
                    adapter_factory(engine, core_app)
                    if adapter_factory
                    else WalletServicesAdapter(engine, core_app=core_app)
                )
                await adapter.initialize()
            else:
                adapter = SimulatedAdapter(engine)
            app.state.adapter = adapter
            task = asyncio.create_task(worker(adapter))
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if settings.wallet_services_enabled:
                await app.state.adapter.close()

    app = FastAPI(title="KiteShield autonomous wallet — " + settings.mode, lifespan=lifespan)
    app.state.engine = engine

    @app.get("/health")
    def health():
        return {
            "profile": settings.wallet_source,
            "mode": settings.mode,
            "enabled": settings.enabled,
            "planner_enabled": settings.planner_enabled,
            "signing": (settings.wallet_source if settings.mode == "SEPOLIA" else "test-key-only")
            if settings.wallet_services_enabled
            else False,
            "workflows_enabled": settings.workflows_enabled,
            "quarantine_enabled": settings.quarantine_enabled,
        }

    @app.put("/mandate", dependencies=[Depends(enabled), Depends(admin)])
    async def mandate(payload: Mandate):
        try:
            if settings.wallet_services_enabled:
                await app.state.adapter.configure(
                    payload.recipient, payload.payment_cap, payload.approval_threshold
                )
            values = payload.model_dump(exclude={"approval_threshold"})
            engine.configure(**values)
        except (ValueError, HumanRequiredError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"mode": settings.mode, "saved": True}

    @app.post("/goals", dependencies=[Depends(enabled), Depends(agent)])
    def goal(payload: Goal):
        try:
            task_id = engine.create(**payload.model_dump())
        except (ValueError, HumanRequiredError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"task_id": task_id, "mode": settings.mode}

    @app.get("/goals/{task_id}", dependencies=[Depends(enabled), Depends(agent)])
    def get(task_id: str):
        try:
            return task_response(engine.get(task_id))
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

    @app.post(
        "/goals/{task_id}/resume-before-signing", dependencies=[Depends(enabled), Depends(admin)]
    )
    async def resume_before_signing(task_id: str):
        adapter = getattr(app.state, "adapter", None)
        if not adapter or not hasattr(adapter, "resume_before_signing"):
            raise HTTPException(503, "PRE_SIGN_RECOVERY_UNAVAILABLE")
        try:
            return await adapter.resume_before_signing(task_id)
        except KeyError as exc:
            raise HTTPException(404, "TASK_NOT_FOUND") from exc
        except HumanRequiredError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/goals/{task_id}/reconcile", dependencies=[Depends(enabled), Depends(agent)])
    async def reconcile(task_id: str):
        from demo_autonomy.sandbox import WaitingError

        adapter = getattr(app.state, "adapter", None)
        if not adapter or not hasattr(adapter, "reconcile_existing_payment"):
            raise HTTPException(503, "READ_ONLY_RECONCILIATION_UNAVAILABLE")
        try:
            return await adapter.reconcile_existing_payment(task_id)
        except KeyError as exc:
            raise HTTPException(404, "TASK_NOT_FOUND") from exc
        except (HumanRequiredError, WaitingError) as exc:
            raise HTTPException(409, str(exc)) from exc

    def workflows():
        if not settings.workflows_enabled:
            raise HTTPException(503, "WORKFLOWS_DISABLED")

    def task_response(task):
        if settings.mode == "SEPOLIA":
            # A funding allowance can exceed JavaScript's exact integer range.
            task["funding_cap"] = str(task["funding_cap"])
        return task

    @app.get("/snapshot", dependencies=[Depends(enabled), Depends(agent)])
    def snapshot():
        with engine.db() as db:
            tasks = [
                task_response(engine.get(r[0]))
                for r in db.execute("SELECT id FROM tasks ORDER BY rowid DESC LIMIT 50")
            ]
            issues = (
                [
                    dict(r)
                    for r in db.execute("SELECT * FROM issues ORDER BY created DESC LIMIT 100")
                ]
                if settings.workflows_enabled
                else []
            )
            mandate_row = db.execute("SELECT * FROM mandates WHERE id=1").fetchone()
            mandate = dict(mandate_row) if mandate_row else None
            if mandate:
                mandate["funding_cap"] = str(mandate["funding_cap"])
            system_events = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM events WHERE task_id='system' ORDER BY id DESC LIMIT 30"
                )
            ]
        return {
            "tasks": tasks,
            "issues": issues,
            "control": engine.control() if settings.workflows_enabled else {},
            "mode": settings.mode,
            "wallet_source": settings.wallet_source,
            "mandate": mandate,
            "system_events": system_events,
        }

    @app.get("/wallet", dependencies=[Depends(enabled), Depends(agent)])
    async def wallet():
        if settings.mode != "SEPOLIA":
            return {"mode": settings.mode}
        return await app.state.adapter.wallet_status()

    class Decision(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        decision: str = Field(pattern="^(APPROVE|REJECT)$")

    @app.post(
        "/approvals/{task_id}/decision",
        dependencies=[Depends(enabled), Depends(workflows), Depends(approver)],
    )
    async def decide(task_id: str, payload: Decision):
        if not settings.wallet_services_enabled:
            raise HTTPException(503, "WALLET_SERVICES_DISABLED")
        try:
            if engine.get(task_id)["state"] != "WAITING_APPROVAL":
                raise HTTPException(409, "TASK_NOT_AWAITING_APPROVAL")
            result = await app.state.adapter.decide(task_id, payload.decision)
            with engine.db() as db:
                engine.event(db, task_id, "HUMAN_DECISION", payload.decision)
                if payload.decision == "REJECT":
                    db.execute(
                        "UPDATE tasks SET state='REJECTED',reason='HUMAN_REJECTED' WHERE id=?",
                        (task_id,),
                    )
                else:
                    db.execute(
                        "UPDATE steps SET lease=NULL WHERE task_id=? AND state='WAITING'",
                        (task_id,),
                    )
            return result
        except KeyError as exc:
            raise HTTPException(404, "TASK_NOT_FOUND") from exc
        except HumanRequiredError as exc:
            raise HTTPException(409, str(exc)) from exc

    class ExternalEvent(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        kind: str = Field(
            pattern="^(text|document|voice|incoming_token|incoming_nft|permission_claim|incoming_token_permission|incoming_nft_permission)$"
        )

    @app.post("/events", dependencies=[Depends(enabled), Depends(workflows), Depends(agent)])
    def external_event(payload: ExternalEvent):
        engine.external_event(payload.kind)
        return {"authority_changed": False, "control": engine.control()}

    @app.post(
        "/quarantine/resume", dependencies=[Depends(enabled), Depends(workflows), Depends(admin)]
    )
    def resume():
        engine.resume()
        return engine.control()

    return app
