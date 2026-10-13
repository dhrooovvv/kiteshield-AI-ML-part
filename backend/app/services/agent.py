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

logger = get_logger("agent")


class LLMProposalOutput(BaseModel):
    """Schema enforced on the LLM structured output."""

    recipient: str = Field(..., description="Destination Ethereum address (0x format)")
    amount_eth: float = Field(..., gt=0, description="Amount of ETH to transfer")
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
        logger.info(
            "Agent processing prompt: '%s'", prompt[:80] + ("..." if len(prompt) > 80 else "")
        )

        if self._api_key and len(self._api_key.strip()) > 5:
            try:
                return await self._call_openai_structured(prompt)
            except Exception as e:
                logger.warning(
                    "OpenAI structured output failed: %s. Falling back to local parser.", e
                )
                return self._parse_with_rules(prompt)
        else:
            logger.info("No OpenAI API key configured. Using deterministic local parser.")
            return self._parse_with_rules(prompt)

    async def _call_openai_structured(self, prompt: str) -> AgentProposalRequest:
        """Call OpenAI API using structured output."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.beta.chat.completions.parse(
            model="gpt-4o",
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
        amount_wei = str(int(round(parsed.amount_eth * 10**18)))
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
        # Find Ethereum address: 0x followed by 40 hex chars
        addr_match = re.search(r"0x[a-fA-F0-9]{40}", prompt)
        if not addr_match:
            raise ValidationError(
                "Could not identify a valid Ethereum destination address in prompt.",
                details={"prompt": prompt},
            )
        raw_address = addr_match.group(0)
        recipient = validate_eth_address(raw_address)

        # Find amount: patterns like '0.05 eth', '1.5 ether', '1000 wei', '0.01'
        eth_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:eth|ether)", prompt, re.IGNORECASE)
        wei_match = re.search(r"(\d+)\s*wei", prompt, re.IGNORECASE)

        if eth_match:
            eth_val = float(eth_match.group(1))
            amount_wei = str(int(round(eth_val * 10**18)))
        elif wei_match:
            amount_wei = str(int(wei_match.group(1)))
        else:
            # Fallback: look for generic decimal number
            num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", prompt)
            if num_match:
                eth_val = float(num_match.group(1))
                amount_wei = str(int(round(eth_val * 10**18)))
            else:
                # Default minimal proposal amount (0.01 ETH)
                amount_wei = str(10_000_000_000_000_000)

        return AgentProposalRequest(
            prompt=prompt,
            recipient=recipient,
            amount_wei=amount_wei,
            chain_id=11155111,
            asset_type=AssetType.NATIVE_ETH,
        )
