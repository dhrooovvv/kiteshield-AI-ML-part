"""Offline challenge artifact only: unsigned session-grant typed data.

NOT accepted by any KiteShield execution endpoint or deployed contract.
No key generation, signing, RPC, deployment, or funds movement.
"""

import argparse
import json

from eth_account.messages import encode_typed_data
from web3 import Web3

from app.schemas import validate_eth_address


def build_manifest(
    *,
    wallet: str,
    session_address: str,
    recipient: str,
    max_payment_wei: str,
    total_budget_wei: str,
    valid_after: int,
    valid_until: int,
    grant_nonce: int,
    policy_version: int,
) -> dict:
    addresses = [validate_eth_address(value) for value in (wallet, session_address, recipient)]
    if any(int(address, 16) == 0 for address in addresses):
        raise ValueError("Zero addresses cannot define a session grant")
    if (
        not max_payment_wei.isascii()
        or not max_payment_wei.isdigit()
        or not total_budget_wei.isascii()
        or not total_budget_wei.isdigit()
        or not 0 < int(max_payment_wei) <= int(total_budget_wei) <= 10**24
    ):
        raise ValueError("Invalid session spending limits")
    if (
        not 0 <= valid_after < valid_until <= valid_after + 3600
        or grant_nonce < 0
        or policy_version < 1
    ):
        raise ValueError("Invalid grant lifetime, nonce, or policy context")
    fields = [
        ("sessionKey", "address"),
        ("recipient", "address"),
        ("maxPaymentWei", "uint256"),
        ("totalBudgetWei", "uint256"),
        ("validAfter", "uint256"),
        ("validUntil", "uint256"),
        ("grantNonce", "uint256"),
        ("policyVersion", "uint256"),
    ]
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "SessionGrant": [{"name": name, "type": kind} for name, kind in fields],
        },
        "primaryType": "SessionGrant",
        "domain": {
            "name": "KiteShieldSessionGrant",
            "version": "1",
            "chainId": 11155111,
            "verifyingContract": addresses[0],
        },
        "message": {
            "sessionKey": addresses[1],
            "recipient": addresses[2],
            "maxPaymentWei": max_payment_wei,
            "totalBudgetWei": total_budget_wei,
            "validAfter": valid_after,
            "validUntil": valid_until,
            "grantNonce": grant_nonce,
            "policyVersion": policy_version,
        },
    }
    message = encode_typed_data(full_message=typed_data)
    digest = Web3.keccak(b"\x19" + message.version + message.header + message.body)
    return {
        "status": "UNSIGNED_NOT_EXECUTABLE",
        "onchain_verifier_implemented": False,
        "erc4337_implemented": False,
        "typed_data": typed_data,
        "digest": "0x" + digest.hex().removeprefix("0x"),
        "required_contract_checks": [
            "owner authorization",
            "session signature",
            "recipient and native-only scope",
            "per-payment and atomic cumulative budget",
            "expiry",
            "grant revocation",
            "grant and execution nonce replay protection",
            "chain and contract domain",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("wallet", "session-address", "recipient", "max-payment-wei", "total-budget-wei"):
        parser.add_argument("--" + field, required=True)
    for field in ("valid-after", "valid-until", "grant-nonce", "policy-version"):
        parser.add_argument("--" + field, required=True, type=int)
    args = vars(parser.parse_args())
    print(json.dumps(build_manifest(**args), indent=2))


if __name__ == "__main__":
    main()
