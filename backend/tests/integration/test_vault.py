"""Security boundary tests with public fixture keys and no network access."""

import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from eth_account import Account
from sqlalchemy import select
from web3 import Web3

from app.core.config import get_settings
from app.exceptions import SigningRejectedError, TokenConsumedError, TokenInvalidError
from app.models import Policy, Proposal, SpendingRecord, VaultOperation, VaultRegistry
from app.schemas import NormalizedAction
from app.schemas.vault import VaultExecutionLimits, VaultKind, VaultPayload
from app.services.blockchain import BlockchainService
from app.services.capability import CapabilityService
from app.services.signer import IsolatedSigner
from app.services.vault import action_for_proposal, artifact, canonical, digest, runtime_hash
from app.services.vault_execution import execute_operation, reconcile_operation, verified_receipt

RECIPIENT = "0x229D5588641f2614e3F486c853D8BA0eC5FFe811"
VAULT = Web3.to_checksum_address("0x" + "d" * 40)
AGENT_KEY = "c" * 64


@pytest_asyncio.fixture
async def vault(test_session, monkeypatch, tmp_path):
    settings = get_settings()
    artifact_path = Path(__file__).parents[2] / "app/contracts/guarded_vault.json"
    key_path = tmp_path / "agent.key"
    key_path.write_text(AGENT_KEY)
    key_path.chmod(0o600)
    values = dict(
        vault_enabled=True,
        autonomy_vault_payments_enabled=True,
        vault_artifact_sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        vault_agent_key_file=str(key_path),
        vault_agent_address=Account.from_key(AGENT_KEY).address,
        vault_fee_budget_wei=10**12,
        vault_escrow_budget_wei=1000,
        vault_agent_gas_budget_wei=1000,
        autonomy_recipient=RECIPIENT,
        execution_mode="sepolia",
    )
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    owner = Account.from_key(settings.signer_private_key).address
    registry = VaultRegistry(
        id="global",
        owner=owner,
        agent=settings.vault_agent_address,
        address=VAULT,
        runtime_hash=runtime_hash(owner),
        epoch=1,
        revision=2,
        configured=True,
    )
    policy = Policy(
        version=1,
        max_amount_wei="1000",
        daily_limit_wei="5000",
        allowed_recipients=json.dumps([RECIPIENT]),
        blocked_recipients="[]",
        escalation_threshold_wei="500",
        is_active=True,
    )
    test_session.add_all([registry, policy])
    await test_session.commit()
    state = dict(
        owner=owner,
        agent=registry.agent,
        recipient=RECIPIENT,
        remaining=1000,
        perPayment=1000,
        expires=int(time.time()) + 1800,
        nonce=0,
        epoch=1,
        paused=False,
        block=5,
        timestamp=int(time.time()),
        balance=1000,
        agent_balance=1000,
    )

    async def observe(*args):
        return state.copy()

    monkeypatch.setattr("app.services.vault.chain_state", observe)
    monkeypatch.setattr("app.api.routes.vault.chain_state", observe)
    return SimpleNamespace(
        settings=settings,
        registry=registry,
        state=state,
        session=test_session,
        key_path=key_path,
        monkeypatch=monkeypatch,
    )


async def payment(vault, *, prepared=True):
    from app.models import PolicyDecision

    session = vault.session
    proposal = Proposal(
        correlation_id="vault-test",
        agent_prompt="Explicit fixture intent",
        recipient=RECIPIENT,
        amount_wei="10",
        chain_id=11155111,
        asset_type="NATIVE_ETH",
        status="ALLOWED",
    )
    session.add(proposal)
    await session.flush()
    payload = VaultPayload(
        kind=VaultKind.PAY,
        owner=vault.registry.owner,
        agent=vault.registry.agent,
        recipient=RECIPIENT,
        vault=VAULT,
        amount_wei=10,
        epoch=1,
        session_nonce=0,
        artifact_hash=vault.settings.vault_artifact_sha256,
    )
    op = VaultOperation(
        id="operation",
        request_key="fixture_payment_key",
        proposal_id=proposal.id,
        kind="PAY",
        payload=canonical(payload.model_dump(mode="json")),
        authority_digest=payload.digest(),
        authorized_by="proposer",
        policy_version=1,
        sender=vault.registry.agent.lower(),
        execution_mode="sepolia",
        status="DRAFT",
    )
    session.add(op)
    await session.flush()
    action = await action_for_proposal(session, proposal)
    session.add(
        PolicyDecision(
            proposal_id=proposal.id,
            decision="ALLOW",
            reason_codes="[]",
            action_digest=action.action_digest_without_nonce(),
            policy_version=1,
        )
    )
    if prepared:
        to, value, data = payload.encode(artifact()["bytecode"])
        op.envelope = canonical(
            dict(
                to=to,
                value=value,
                data=data,
                nonce=0,
                gas=100000,
                maxFeePerGas=10,
                maxPriorityFeePerGas=1,
                chainId=11155111,
                type=2,
            )
        )
        op.nonce, op.status = 0, "PREPARED"
        session.add(
            SpendingRecord(
                id=op.id,
                proposal_id=proposal.id,
                amount_wei="10",
                status="RESERVED",
                period_date="2026-11-02",
            )
        )
    await session.commit()
    return proposal, op, action


@pytest.mark.asyncio
async def test_off_by_default_and_artifact_pin(vault):
    from app.core.config import Settings

    assert Settings.model_fields["vault_enabled"].default is False
    assert Settings.model_fields["autonomy_vault_payments_enabled"].default is False
    vault.monkeypatch.setattr(vault.settings, "vault_artifact_sha256", "0" * 64)
    with pytest.raises(SigningRejectedError, match="pin mismatch"):
        artifact()


@pytest.mark.asyncio
async def test_owner_controls_require_administrator_and_idempotency(client, vault):
    settings = vault.settings
    for key in (settings.api_key, settings.approver_api_key):
        response = await client.post(
            "/api/v1/vault/owner-intents",
            headers={"X-API-Key": key},
            json={"request_key": "owner_deposit_test", "kind": "DEPOSIT", "amount_wei": 100},
        )
        assert response.status_code == 403
    headers = {"X-API-Key": settings.policy_admin_api_key}
    request = dict(request_key="owner_deposit_test", kind="DEPOSIT", amount_wei=100)
    response = await client.post("/api/v1/vault/owner-intents", headers=headers, json=request)
    assert response.status_code == 200, response.text
    first = response.json()["data"]
    again = await client.post("/api/v1/vault/owner-intents", headers=headers, json=request)
    assert again.json()["data"]["id"] == first["id"]
    conflict = await client.post(
        "/api/v1/vault/owner-intents", headers=headers, json={**request, "amount_wei": 101}
    )
    assert conflict.status_code >= 400
    denied = await client.post(
        "/api/v1/vault/owner-intents",
        headers=headers,
        json={**request, "request_key": "owner_resume_test", "kind": "PAY", "amount_wei": 0},
    )
    assert denied.status_code >= 400


@pytest.mark.asyncio
async def test_exact_capability_is_single_use_and_native_audience_rejects_it(vault):
    proposal, op, action = await payment(vault)
    service = CapabilityService()
    signer = IsolatedSigner(service)
    token, _ = await service.issue_vault_token(vault.session, op, BlockchainService())
    with pytest.raises(TokenInvalidError):
        service.verify_token(token)
    with pytest.raises(TokenInvalidError, match="namespace"):
        await service.issue_token(vault.session, action, 1)
    with pytest.raises(SigningRejectedError, match="native signing path"):
        await signer.sign_transaction(vault.session, token, action)
    signed = await signer.sign_vault_operation(vault.session, token, op.id, BlockchainService())
    assert Account.recover_transaction(signed["raw_transaction"]).lower() == op.sender
    op.status = "PREPARED"  # Even if a caller resets status, consumption survives.
    with pytest.raises(TokenConsumedError):
        await signer.sign_vault_operation(vault.session, token, op.id, BlockchainService())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("data", "0x"),
        ("value", 10),
        ("to", RECIPIENT),
        ("nonce", 1),
        ("chainId", 1),
        ("gas", 3000000),
        ("maxFeePerGas", 10**15),
        ("maxPriorityFeePerGas", 0),
    ],
)
async def test_signer_rejects_mutated_envelope(vault, field, value):
    _, op, _ = await payment(vault)
    service = CapabilityService()
    token, _ = await service.issue_vault_token(vault.session, op, BlockchainService())
    tx = json.loads(op.envelope)
    tx[field] = value
    op.envelope = canonical(tx)
    await vault.session.flush()
    with pytest.raises(SigningRejectedError):
        await IsolatedSigner(service).sign_vault_operation(
            vault.session, token, op.id, BlockchainService()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["epoch", "expiry", "paused", "remaining", "policy", "payload", "identity"]
)
async def test_independent_signer_rechecks_authority(vault, change):
    _, op, _ = await payment(vault)
    service = CapabilityService()
    token, _ = await service.issue_vault_token(vault.session, op, BlockchainService())
    if change == "epoch":
        vault.state["epoch"] = 2
    if change == "expiry":
        vault.state["expires"] = int(time.time()) - 1
    if change == "paused":
        vault.state["paused"] = True
    if change == "remaining":
        vault.state["remaining"] = 0
    if change == "policy":
        policy = await vault.session.scalar(select(Policy))
        policy.version = 2
    if change == "payload":
        payload = json.loads(op.payload)
        payload["amount_wei"] = 11
        op.payload = canonical(payload)
    if change == "identity":
        vault.monkeypatch.setattr(vault.settings, "vault_agent_address", vault.registry.owner)
    await vault.session.flush()
    with pytest.raises(SigningRejectedError):
        await IsolatedSigner(service).sign_vault_operation(
            vault.session, token, op.id, BlockchainService()
        )


@pytest.mark.asyncio
async def test_tighten_never_expands_and_agent_cannot_resume(vault):
    from app.services.vault import validate_operation

    for kind, expected in [(VaultKind.TIGHTEN, True), (VaultKind.RESUME, False)]:
        payload = VaultPayload(
            kind=kind,
            owner=vault.registry.owner,
            agent=vault.registry.agent,
            recipient=RECIPIENT,
            vault=VAULT,
            epoch=1,
            budget_wei=900 if kind == VaultKind.TIGHTEN else 0,
            per_payment_wei=500 if kind == VaultKind.TIGHTEN else 0,
            expires=vault.state["expires"] - 10 if kind == VaultKind.TIGHTEN else 0,
            artifact_hash=vault.settings.vault_artifact_sha256,
        )
        op = VaultOperation(
            id="tighten",
            request_key="tighten_fixture_key",
            kind=kind.value,
            payload=canonical(payload.model_dump(mode="json")),
            authority_digest=payload.digest(),
            authorized_by="proposer",
            policy_version=1,
            sender=vault.registry.agent.lower(),
            execution_mode="sepolia",
            status="DRAFT",
        )
        if expected:
            await validate_operation(vault.session, op, BlockchainService())
            changed = payload.model_copy(update={"budget_wei": 1001})
            op.payload, op.authority_digest = (
                canonical(changed.model_dump(mode="json")),
                changed.digest(),
            )
        with pytest.raises(SigningRejectedError):
            await validate_operation(vault.session, op, BlockchainService())


@pytest.mark.asyncio
async def test_native_approval_digest_does_not_authorize_vault(vault):
    from app.models import ApprovalRequest, PolicyDecision
    from app.services.authorization import validate_authorization

    proposal, op, action = await payment(vault)
    policy = await vault.session.scalar(select(Policy))
    policy.escalation_threshold_wei = "5"
    decision = await vault.session.scalar(select(PolicyDecision))
    decision.decision = "ESCALATE"
    proposal.status = "APPROVED"
    native = NormalizedAction(
        proposal_id=proposal.id,
        correlation_id=proposal.correlation_id,
        recipient=RECIPIENT,
        amount_wei=10,
        chain_id=11155111,
    )
    approval = ApprovalRequest(
        proposal_id=proposal.id,
        action_digest=native.action_digest_without_nonce(),
        policy_version=1,
        status="APPROVED",
        approved_by="human_approver",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    vault.session.add(approval)
    await vault.session.flush()
    from app.exceptions import ApprovalRequiredError

    with pytest.raises(ApprovalRequiredError):
        await validate_authorization(vault.session, action, 1, approval.id)
    approval.action_digest = action.action_digest_without_nonce()
    await vault.session.flush()
    await validate_authorization(vault.session, action, 1, approval.id)


@pytest.mark.asyncio
async def test_unknown_broadcast_never_signs_or_broadcasts_a_second_time(vault):
    _, op, _ = await payment(vault)
    sends = []

    class Eth:
        chain_id = 11155111

        def send_raw_transaction(self, raw):
            sends.append(raw)
            raise TimeoutError("unknown delivery")

    blockchain = BlockchainService()
    blockchain._w3 = SimpleNamespace(eth=Eth())
    service = CapabilityService()
    from app.exceptions import TransactionSubmissionError
    from app.services.audit import AuditService

    with pytest.raises(TransactionSubmissionError):
        await execute_operation(
            vault.session, op, service, IsolatedSigner(service), blockchain, AuditService()
        )
    assert op.status == "UNCERTAIN" and op.raw_transaction and op.tx_hash
    original = op.raw_transaction

    async def no_receipt(*args):
        return None

    vault.monkeypatch.setattr("app.services.vault_execution.verified_receipt", no_receipt)
    await execute_operation(
        vault.session, op, service, IsolatedSigner(service), blockchain, AuditService()
    )
    assert sends == [bytes.fromhex(original.removeprefix("0x"))]
    assert op.raw_transaction == original and op.status == "UNCERTAIN"


@pytest.mark.asyncio
async def test_native_nonce_allocation_blocks_pending_vault(vault):
    _, op, _ = await payment(vault)
    vault.monkeypatch.setattr(vault.settings, "execution_mode", "simulated")
    op.execution_mode = "simulated"
    await vault.session.flush()
    action = NormalizedAction(
        proposal_id="native",
        correlation_id="native",
        recipient=RECIPIENT,
        amount_wei=10,
        chain_id=11155111,
    )
    from app.exceptions import TransactionSubmissionError

    with pytest.raises(TransactionSubmissionError, match="pending vault"):
        await BlockchainService().prepare_transaction(vault.session, vault.registry.agent, action)


def receipt_rpc(vault, op, *, event=True, canonical_block=True):
    from eth_abi import encode
    from hexbytes import HexBytes

    tx = json.loads(op.envelope)
    block_hash = HexBytes("0x" + "a" * 64)
    tx_hash = HexBytes("0x" + "b" * 64)
    op.tx_hash = tx_hash.to_0x_hex()
    op.status = "SUBMITTED"
    code = bytearray.fromhex(artifact()["runtime"].removeprefix("0x"))
    for refs in artifact()["immutable_references"].values():
        for ref in refs:
            code[ref["start"] : ref["start"] + 32] = bytes.fromhex(vault.registry.owner[2:]).rjust(
                32, b"\0"
            )
    logs = (
        [
            dict(
                address=VAULT,
                topics=[
                    Web3.keccak(text="Paid(address,uint256,uint256)"),
                    HexBytes(bytes.fromhex(RECIPIENT[2:]).rjust(32, b"\0")),
                ],
                data=HexBytes(encode(["uint256"] * 2, [10, 0])),
            )
        ]
        if event
        else []
    )
    receipt = dict(
        transactionHash=tx_hash,
        blockHash=block_hash,
        blockNumber=5,
        status=1,
        gasUsed=50000,
        effectiveGasPrice=5,
        logs=logs,
    )
    transaction = {
        **tx,
        "input": HexBytes(tx["data"]),
        "from": vault.registry.agent,
        "hash": tx_hash,
        "blockHash": block_hash,
        "blockNumber": 5,
    }
    return SimpleNamespace(
        eth=SimpleNamespace(
            chain_id=11155111,
            get_transaction_receipt=lambda _: receipt,
            get_transaction=lambda _: transaction,
            get_block=lambda _: dict(
                hash=block_hash if canonical_block else HexBytes("0x" + "f" * 64)
            ),
            get_code=lambda *args, **kwargs: bytes(code),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("event,block", [(False, True), (True, False)])
async def test_receipt_requires_paid_event_and_canonical_block(vault, event, block):
    _, op, _ = await payment(vault)
    blockchain = BlockchainService()
    blockchain._w3 = receipt_rpc(vault, op, event=event, canonical_block=block)
    from app.exceptions import RPCError

    with pytest.raises(RPCError):
        await verified_receipt(op, blockchain)


@pytest.mark.asyncio
async def test_receipt_reconciles_once_without_signing(vault):
    from app.models import Transaction
    from app.services.audit import AuditService

    proposal, op, _ = await payment(vault)
    blockchain = BlockchainService()
    blockchain._w3 = receipt_rpc(vault, op)
    vault.session.add(
        Transaction(
            proposal_id=proposal.id,
            tx_hash=op.tx_hash,
            status="SUBMITTED",
            execution_mode="sepolia",
            execution_outcome="SUBMITTED",
        )
    )
    await vault.session.commit()
    assert await reconcile_operation(vault.session, op, blockchain, AuditService())
    assert await reconcile_operation(vault.session, op, blockchain, AuditService())
    assert op.status == "CONFIRMED" and proposal.status == "CONFIRMED"
    assert (await vault.session.get(SpendingRecord, op.id)).status == "COMMITTED"


@pytest.mark.asyncio
async def test_limit_digest_cannot_be_retargeted(vault):
    _, op, _ = await payment(vault)
    limits = VaultExecutionLimits(
        operation_id=op.id,
        payload_digest=op.authority_digest,
        envelope_digest=digest(op.envelope),
        max_fee_wei=1000000,
    )
    limits.check(op)
    op.id = "other-operation"
    with pytest.raises(SigningRejectedError):
        limits.check(op)


@pytest.mark.asyncio
async def test_http_payout_pipeline_keeps_original_owner_and_confirms_paid_event(client, vault):
    from hexbytes import HexBytes

    from app.api.routes import vault as routes

    sends = []

    class Eth:
        chain_id = 11155111
        max_priority_fee = 1

        def estimate_gas(self, request):
            assert request["to"] == VAULT and request["value"] == 0
            return 50000

        def get_block(self, _):
            return {"baseFeePerGas": 4}

        def get_transaction_count(self, *args):
            return 0

        def get_balance(self, _):
            return 10**9

        def send_raw_transaction(self, raw):
            sends.append(raw)
            return Web3.keccak(raw)

    vault.monkeypatch.setattr(routes.blockchain, "_w3", SimpleNamespace(eth=Eth()))
    headers = {"X-API-Key": vault.settings.api_key}
    request = dict(
        request_key="http_pipeline_fixture", amount_wei=10, expected_epoch=1, expected_revision=2
    )
    created = await client.post("/api/v1/vault/payments", headers=headers, json=request)
    assert created.status_code == 200, created.text
    op = created.json()["data"]
    evaluated = await client.post(
        f"/api/v1/proposals/{op['proposal_id']}/evaluate", headers=headers
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["data"]["status"] == "ALLOWED"
    # A vault proposal cannot be converted into an EOA payment by using the old endpoint.
    denied = await client.post(f"/api/v1/proposals/{op['proposal_id']}/sign", headers=headers)
    assert denied.status_code >= 400
    prepared = await client.post(f"/api/v1/vault/operations/{op['id']}/prepare", headers=headers)
    assert prepared.status_code == 200, prepared.text
    op = prepared.json()["data"]
    limits = dict(
        operation_id=op["id"],
        payload_digest=op["payload_digest"],
        envelope_digest=op["envelope_digest"],
        max_fee_wei=10**7,
    )
    submitted = await client.post(
        f"/api/v1/vault/operations/{op['id']}/execute", headers=headers, json=limits
    )
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()["data"]
    assert result["status"] == "SUBMITTED" and len(sends) == 1
    assert "raw_transaction" not in result and "key" not in result
    assert Account.recover_transaction(sends[0]).lower() == vault.registry.agent.lower()
    assert Account.from_key(vault.settings.signer_private_key).address == vault.registry.owner
    stored = await vault.session.get(VaultOperation, op["id"], populate_existing=True)
    rpc = receipt_rpc(vault, stored)
    # Bind fixture proof to the hash of the bytes this pipeline actually signed.
    tx_hash = HexBytes(Web3.keccak(sends[0]))
    stored.tx_hash = tx_hash.to_0x_hex()
    receipt = rpc.eth.get_transaction_receipt(None)
    receipt["transactionHash"] = tx_hash
    tx = rpc.eth.get_transaction(None)
    tx["hash"] = tx_hash
    rpc.eth.get_transaction = lambda _: tx
    await vault.session.commit()
    vault.monkeypatch.setattr(routes.blockchain, "_w3", rpc)
    reconciled = await client.post(
        f"/api/v1/vault/operations/{op['id']}/reconcile", headers=headers
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["data"]["status"] == "CONFIRMED"
    again = await client.post(
        f"/api/v1/vault/operations/{op['id']}/execute", headers=headers, json=limits
    )
    assert again.status_code == 200 and len(sends) == 1


@pytest.mark.asyncio
async def test_owner_deployment_has_separate_gas_cap(vault):
    vault.registry.address, vault.registry.epoch, vault.registry.configured = None, 0, False
    payload = VaultPayload(
        kind=VaultKind.DEPLOY,
        owner=vault.registry.owner,
        agent=vault.registry.agent,
        recipient=RECIPIENT,
        epoch=0,
        artifact_hash=vault.settings.vault_artifact_sha256,
    )
    _, _, data = payload.encode(artifact()["bytecode"])
    op = VaultOperation(
        id="deployment",
        request_key="owner_deployment_fixture",
        kind="DEPLOY",
        payload=canonical(payload.model_dump(mode="json")),
        authority_digest=payload.digest(),
        authorized_by="policy_administrator",
        policy_version=1,
        sender=vault.registry.owner.lower(),
        execution_mode="sepolia",
        status="PREPARED",
        nonce=0,
        envelope=canonical(
            dict(
                value=0,
                data=data,
                chainId=11155111,
                nonce=0,
                gas=6500000,
                maxFeePerGas=10,
                maxPriorityFeePerGas=1,
                type=2,
            )
        ),
    )
    vault.session.add(op)
    await vault.session.commit()
    service = CapabilityService()
    token, _ = await service.issue_vault_token(vault.session, op, BlockchainService())
    signed = await IsolatedSigner(service).sign_vault_operation(
        vault.session, token, op.id, BlockchainService()
    )
    assert (
        Account.recover_transaction(signed["raw_transaction"]).lower()
        == vault.registry.owner.lower()
    )
    assert vault.settings.vault_max_gas_units == 1000000


@pytest.mark.asyncio
async def test_owner_can_pause_without_agent_gas_but_proposer_cannot_impersonate_owner(vault):
    from app.services.vault import validate_operation

    vault.state["agent_balance"] = 0
    payload = VaultPayload(
        kind=VaultKind.OWNER_PAUSE,
        owner=vault.registry.owner,
        agent=vault.registry.agent,
        recipient=RECIPIENT,
        vault=VAULT,
        epoch=1,
        artifact_hash=vault.settings.vault_artifact_sha256,
    )
    assert not payload.agent_operation
    to, value, data = payload.encode(artifact()["bytecode"])
    assert to == VAULT and value == 0 and len(data) == 10
    op = VaultOperation(
        id="owner-pause",
        request_key="owner_pause_fixture",
        kind="OWNER_PAUSE",
        payload=canonical(payload.model_dump(mode="json")),
        authority_digest=payload.digest(),
        authorized_by="policy_administrator",
        policy_version=1,
        sender=vault.registry.owner.lower(),
        execution_mode="sepolia",
        status="DRAFT",
    )
    await validate_operation(vault.session, op, BlockchainService())
    op.authorized_by = "proposer"
    with pytest.raises(SigningRejectedError, match="administrator"):
        await validate_operation(vault.session, op, BlockchainService())
