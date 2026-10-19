"""Read-only demo preparation. Never initializes DB, creates a mandate, or signs."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.services.treasury import observe, policy_allows, sender_address  # noqa: E402


async def preview():
    s = get_settings()
    engine = create_async_engine(s.database_url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    config = {
        "sender": sender_address(),
        "recipient": "0x229D5588641f2614e3F486c853D8BA0eC5FFe811",
        "chain_id": 11155111,
        "target_balance_wei": "0",
        "sweep_maximum_wei": "30000000000000",
        "minimum_excess_wei": "20000000000000",
        "cooldown_seconds": 600,
        "daily_action_limit": 3,
        "freshness_seconds": 60,
    }
    try:
        snapshot = await observe(config, factory)
        result = {"persisted": False, "activated": False, "observation": snapshot}
        if snapshot.get("status") == "available":
            balance = int(snapshot["balance_wei"])
            if balance < 40000000000000:
                result["reason"] = "INSUFFICIENT_BALANCE_FOR_REQUESTED_TARGET"
            else:
                config["target_balance_wei"] = str(balance - 40000000000000)
                result["proposed_configuration"] = config
                async with factory() as session:
                    _, _, allowed = await policy_allows(session, config, 30000000000000)
                result["policy_scope_allowed"] = allowed
                result["available_excess_after_fees_wei"] = str(
                    40000000000000 - int(snapshot.get("maximum_fee_reserve_wei", "0"))
                )
        print(json.dumps(result, indent=2))
    except Exception:
        print(
            json.dumps(
                {"persisted": False, "activated": False, "reason": "READ_ONLY_PREVIEW_UNAVAILABLE"}
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(preview())
