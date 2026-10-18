"""
KiteShield Wallet — AI Agent Service

Translates natural language instructions into structured transaction proposals.
Enforces strict boundaries:
- Security Invariant SI-1: Model output is strictly untrusted.
- Private keys are NEVER exposed to the LLM.
- Output is parsed and schema-validated before returning.
- Operates in mock/fallback mode when OPENAI_API_KEY is not configured or in tests.
"""

import re

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.exceptions import ValidationError
from app.schemas import AgentProposalRequest, AssetType, validate_eth_address
from app.services.amounts import eth_to_wei

logger = get_logger("agent")


class LLMProposalOutput(BaseModel):
    """Schema enforced on the LLM structured output."""

    recipient: str = Field(..., description="Destination Ethereum address (0x format)")
    amount_eth: str = Field(..., description="Exact positive decimal ETH string, not a number")
    explanation: str = Field(..., description="Agent reasoning or summary of the action")


class AgentService:
    """Agent service converting natural language prompts to transaction proposals."""

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.openai_api_key

    async def propose_transaction_from_prompt(
        self,
        prompt: str,
    ) -> AgentProposalRequest:
        """Parse natural language into a validated AgentProposalRequest.

        Uses OpenAI structured output if an API key is present.
        Falls back to local rule-based parsing if no API key is set.
        """
        # Require explicit, unambiguous intent even when an LLM is configured.
        expected = self._parse_with_rules(prompt)
        if self._api_key and len(self._api_key.strip()) > 5:
            try:
                extracted = await self._call_openai_structured(prompt)
            except Exception as exc:
                raise ValidationError("Transaction extraction failed; no proposal created") from exc
            if (extracted.recipient.lower(), extracted.amount_wei) != (
                expected.recipient.lower(),
                expected.amount_wei,
            ):
                raise ValidationError("Model extraction conflicts with explicit payment intent")
            return extracted
        return expected

    async def _call_openai_structured(self, prompt: str) -> AgentProposalRequest:
        """Call OpenAI API using structured output."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.beta.chat.completions.parse(
            model=get_settings().openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are KiteShield Agent. Your sole role is to extract "
                        "Ethereum transaction parameters from natural language "
                        "requests on Sepolia testnet. You cannot authorize, "
                        "sign, or execute transactions. Extract destination "
                        "address and amount of ETH to send."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format=LLMProposalOutput,
            temperature=0.0,
        )

        parsed: LLMProposalOutput = response.choices[0].message.parsed
        if not parsed:
            raise ValidationError("Agent failed to parse structured output from model")

        # Convert ETH float to exact wei integer string
        amount_wei = eth_to_wei(parsed.amount_eth)
        checksummed_recipient = validate_eth_address(parsed.recipient)

        return AgentProposalRequest(
            prompt=prompt,
            recipient=checksummed_recipient,
            amount_wei=amount_wei,
            chain_id=11155111,
            asset_type=AssetType.NATIVE_ETH,
        )

    def _parse_with_rules(self, prompt: str) -> AgentProposalRequest:
        """Deterministic regex-based extraction for offline, mock, and test environments."""
        addresses = re.findall(r"0x[a-fA-F0-9]{40}(?![a-fA-F0-9])", prompt)
        if len(addresses) != 1:
            raise ValidationError("Specify exactly one complete recipient address")
        recipient = validate_eth_address(addresses[0])
        amount_wei = self.extract_explicit_amount(prompt)
        return AgentProposalRequest(
            prompt=prompt,
            recipient=recipient,
            amount_wei=amount_wei,
            chain_id=11155111,
            asset_type=AssetType.NATIVE_ETH,
        )

    @staticmethod
    def extract_explicit_amount(prompt: str) -> str:
        if re.search(
            r"[-−–]\s*(?:\d|\.)|\b(?:negative|approximately|about|between|up to)\b",
            prompt,
            re.IGNORECASE,
        ):
            raise ValidationError(
                "Approximate, ranged, or negative amounts are not executable intent"
            )

        pattern = r"(?<![\w.,])([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ether|eth|wei)\b"
        amounts = re.findall(
            r"(?<![\w.,])([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ether|eth|wei)\b",
            prompt,
            re.IGNORECASE,
        )
        if len(amounts) != 1:
            raise ValidationError("Specify exactly one explicit ETH or wei amount")
        remaining = re.sub(pattern, "", prompt, flags=re.IGNORECASE)
        remaining = re.sub(r"0x[a-fA-F0-9]{40}", "", remaining)
        if re.search(r"(?<!\w)(?:\d|\.\d)", remaining):
            raise ValidationError("Additional numbers make this payment intent ambiguous")
        value, unit = amounts[0]
        if unit.lower() == "wei":
            if not re.fullmatch(r"[0-9]+", value) or not 0 < int(value) <= 10**24:
                raise ValidationError("Wei must be a positive integer within the supported limit")
            amount_wei = str(int(value))
        else:
            amount_wei = eth_to_wei(value)
        return amount_wei
