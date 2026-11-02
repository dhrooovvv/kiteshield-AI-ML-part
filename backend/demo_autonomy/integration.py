"""Main-app wiring. Deliberately refuses live/funded profiles before any new DB write."""

import tempfile
from pathlib import Path

from demo_autonomy.engine import Settings
from demo_autonomy.server import create_demo


def mount_autonomy(app, settings):
    if settings.execution_mode == "sepolia" and getattr(settings, "autonomy_live_enabled", False):
        from demo_autonomy.main_wallet import mount_main_wallet

        return mount_main_wallet(app, settings)
    directory = Path(settings.autonomy_profile_dir).resolve()
    database = settings.database_url.removeprefix("sqlite+aiosqlite:///")
    wallet_path = Path(database).resolve()
    if (
        settings.execution_mode != "simulated"
        or settings.app_env != "test"
        or settings.app_port != 8001
        or settings.signer_private_key != "b" * 64
        or not directory.is_relative_to(Path(tempfile.gettempdir()).resolve())
        or not directory.name.startswith("kiteshield-gate-main-")
        or wallet_path.parent != directory
        or wallet_path.name != "wallet-simulation.sqlite3"
    ):
        raise RuntimeError("Main autonomy is restricted to the isolated 8001 test profile")
    child = create_demo(
        Settings(
            directory,
            enabled=True,
            planner_enabled=True,
            model=settings.autonomy_model,
            model_digest=settings.autonomy_model_digest,
            ollama_version=settings.autonomy_ollama_version,
            workflows_enabled=True,
            quarantine_enabled=settings.autonomy_quarantine_enabled,
            wallet_services_enabled=True,
        ),
        settings.policy_admin_api_key,
        settings.api_key,
        settings.approver_api_key,
        core_app=app,
    )
    app.state.autonomy_app = child
    app.mount("/api/v1/autonomy", child)


async def assistant_goal(app, prompt, actor):
    """Route explicit multi-step goals; ordinary assistant queries keep their old path."""
    import hashlib
    import re

    if not re.match(r"^fund(?: my wallet)? if needed,", prompt, re.I):
        return None
    from fastapi import HTTPException

    from app.core.security import require_proposer
    from demo_autonomy.engine import HumanRequiredError

    await require_proposer(actor)
    engine = app.state.autonomy_app.state.engine
    # Network retries retrieve one durable task. The task page provides an explicit
    # fresh request key when the operator actually wants a separate repeated task.
    key = "assistant_" + hashlib.sha256((actor + "\n" + prompt).encode()).hexdigest()
    try:
        task_id = engine.create(prompt, key)
    except (ValueError, HumanRequiredError) as exc:
        raise HTTPException(422, str(exc)) from exc
    task = engine.get(task_id)
    return {
        "kind": "autonomous_task",
        "title": "Autonomous task",
        "message": "Follow progress here or in Autonomous Tasks. "
        "Permitted steps proceed automatically; human approval remains separate.",
        "data": {"task_id": task_id, "state": task["state"], "mode": engine.settings.mode},
    }
