import json
import uuid
from dataclasses import replace

import httpx
import pytest

from demo_autonomy.commerce import GOAL, PRICE, Commerce
from demo_autonomy.engine import Engine, HumanRequiredError, Settings
from demo_autonomy.server import create_demo


class VaultEngine(Engine):
    def context_for_new_task(self):
        return {"backend": "VAULT"}


@pytest.fixture
def shop(tmp_path):
    engine = VaultEngine(Settings(tmp_path, enabled=True, commerce_enabled=True, mode="SEPOLIA"))
    engine.initialize()
    engine.configure("Acme", "0x" + "1" * 40, PRICE * 3, 0)
    commerce = Commerce(engine)
    commerce.initialize()
    return commerce


def purchase(shop, scenario="standard"):
    return shop.create(str(uuid.uuid4()), GOAL, scenario)


def verified(shop, order, tx_hash="0x" + "a" * 64):
    evidence = {
        "mode": "SEPOLIA",
        "payment_backend": "VAULT",
        "verified": True,
        "recipient": order["quote"]["recipient"],
        "paid_wei": PRICE,
        "tx_hash": tx_hash,
    }
    with shop.engine.db() as db:
        db.execute("UPDATE tasks SET state='COMPLETED' WHERE id=?", (order["task_id"],))
        for position, tool in enumerate(("payment", "receipt")):
            db.execute(
                "INSERT INTO steps VALUES(?,?,?,'COMPLETED',NULL,NULL,?)",
                (order["task_id"], position, tool, json.dumps(evidence | {"tool": tool})),
            )


def test_purchase_delivers_once_and_survives_restart(shop):
    order = purchase(shop)
    assert order["artifact"] is None
    verified(shop, order)
    restored = Commerce(VaultEngine(shop.engine.settings))
    delivered = restored.get(order["id"])
    assert delivered["state"] == "DELIVERED"
    assert delivered["artifact"]["content"].startswith("# Developer field guide")
    assert restored.create(order["id"], GOAL)["receipt"] == delivered["receipt"]
    assert sum(e["kind"] == "PRODUCT_DELIVERED" for e in restored.get(order["id"])["events"]) == 1
    with shop.engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


def test_tampered_checkout_never_creates_task_and_cannot_be_reopened(shop):
    order = purchase(shop, "tampered")
    assert order["state"] == "BLOCKED"
    assert order["reason"] == "CHECKOUT_TOTAL_CHANGED"
    assert order["task_id"] is None
    with pytest.raises(HumanRequiredError):
        shop.checkout(
            order["id"], order["quote"]["digest"], str(PRICE), order["quote"]["recipient"]
        )
    with shop.engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_attack_after_delivery_keeps_original_order(shop):
    order = purchase(shop)
    verified(shop, order)
    shop.get(order["id"])
    with pytest.raises(HumanRequiredError, match="CHECKOUT_TOTAL_CHANGED"):
        shop.checkout(
            order["id"], order["quote"]["digest"], str(PRICE + 1), order["quote"]["recipient"]
        )
    assert shop.get(order["id"])["state"] == "DELIVERED"


def test_no_delivery_for_mismatching_or_simulated_receipt(shop):
    order = purchase(shop)
    verified(shop, order)
    with shop.engine.db() as db:
        db.execute(
            "UPDATE steps SET result=? WHERE task_id=? AND tool='receipt'",
            (json.dumps({"verified": True, "mode": "SIMULATED"}), order["task_id"]),
        )
    result = shop.get(order["id"])
    assert result["reason"] == "PAYMENT_EVIDENCE_MISMATCH"
    assert result["artifact"] is None


def test_same_transaction_cannot_fulfill_two_orders(shop):
    first, second = purchase(shop), purchase(shop)
    verified(shop, first)
    verified(shop, second)
    assert shop.get(first["id"])["delivered"]
    result = shop.get(second["id"])
    assert result["reason"] == "PAYMENT_ALREADY_CLAIMED"
    assert result["artifact"] is None


def test_native_live_backend_never_creates_purchase_task(shop):
    native = Commerce(Engine(shop.engine.settings))
    order = purchase(native)
    assert order["reason"] == "COMMERCE_VAULT_REQUIRED"
    with shop.engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_mandate_change_between_quote_and_task_is_atomic(shop, monkeypatch):
    original = shop.engine.create

    def changed(*args, **kwargs):
        shop.engine.configure("Acme", "0x" + "2" * 40, PRICE * 3, 0)
        return original(*args, **kwargs)

    monkeypatch.setattr(shop.engine, "create", changed)
    result = purchase(shop)
    assert result["reason"] == "MERCHANT_QUOTE_AUTHORITY_CHANGED"
    with shop.engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_restart_after_quote_before_task_and_after_task_before_link(shop, monkeypatch):
    original = shop.checkout
    monkeypatch.setattr(
        shop, "checkout", lambda *args: (_ for _ in ()).throw(RuntimeError("crash"))
    )
    order_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        shop.create(order_id, GOAL)
    monkeypatch.setattr(shop, "checkout", original)
    shop.resume_pending()
    order = shop.get(order_id)
    assert order["task_id"]
    with shop.engine.db() as db:
        db.execute("UPDATE commerce_orders SET task_id=NULL,state='QUOTED' WHERE id=?", (order_id,))
    assert shop.get(order_id)["task_id"] == order["task_id"]
    assert shop.create(order_id, GOAL)["task_id"] == order["task_id"]


@pytest.mark.asyncio
async def test_routes_require_flag_and_proposer(tmp_path):
    settings = Settings(tmp_path, enabled=True)
    app = create_demo(settings, "admin-token-" * 4, "agent-token-" * 4)
    app.state.engine.initialize()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/commerce/catalog")).status_code == 403
        response = await client.get(
            "/commerce/catalog", headers={"Authorization": "Bearer " + "agent-token-" * 4}
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "COMMERCE_DISABLED"


def test_simulated_flow_has_no_live_delivery(shop):
    simulation = Commerce(VaultEngine(replace(shop.engine.settings, mode="SIMULATED")))
    order = purchase(simulation)
    verified(simulation, order)
    result = simulation.get(order["id"])
    assert result["state"] == "SIMULATED"
    assert not result["delivered"] and result["artifact"] is None


def test_concurrent_same_order_creates_one_task(shop):
    from concurrent.futures import ThreadPoolExecutor

    order_id = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        orders = list(pool.map(lambda _: shop.create(order_id, GOAL), range(4)))
    assert len({order["task_id"] for order in orders}) == 1
    with shop.engine.db() as db:
        assert db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


def test_preclaimed_request_key_cannot_bypass_quote_binding(shop):
    order_id = str(uuid.uuid4())
    goal = f"fund if needed, pay supplier Acme {PRICE} wei, verify"
    task_id = shop.engine.create(goal, "purchase_" + order_id)
    shop.engine.configure("Acme", "0x" + "2" * 40, PRICE * 3, 0)
    result = shop.create(order_id, GOAL)
    assert result["task_id"] is None
    assert result["reason"] == "MERCHANT_QUOTE_AUTHORITY_CHANGED"
    assert shop.engine.get(task_id)["state"] == "PLANNING"
