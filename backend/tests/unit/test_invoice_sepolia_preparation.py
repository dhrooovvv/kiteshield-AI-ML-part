"""Preparation cannot silently activate invoice or standing treasury payments."""

from copy import deepcopy

import pytest

from app.core.config import get_settings
from scripts.run_invoice_sepolia_preview import preparation_settings


def test_preparation_uses_live_chain_but_disables_all_automation(tmp_path):
    settings = deepcopy(get_settings())
    settings.execution_mode = "sepolia"
    settings.auto_execute_enabled = True
    settings.treasury_monitor_enabled = True
    settings.invoice_inbox = str(tmp_path / "persistent-inbox")
    settings.invoice_search_roots = [str(tmp_path / "approved-documents")]
    limits = (
        settings.max_gas_units,
        settings.max_fee_per_gas_wei,
        settings.max_priority_fee_per_gas_wei,
        settings.auto_execute_max_eth,
    )
    identities = (
        settings.signer_private_key,
        settings.api_key,
        settings.approver_api_key,
        settings.policy_admin_api_key,
        settings.database_url,
    )
    result = preparation_settings(settings)
    assert result.execution_mode == "sepolia"
    assert result.invoice_intake_enabled and result.invoice_learned_screening_enabled
    assert not any(
        (
            result.invoice_auto_execute_enabled,
            result.invoice_live_execution_enabled,
            result.auto_execute_enabled,
            result.treasury_monitor_enabled,
        )
    )
    assert limits == (
        result.max_gas_units,
        result.max_fee_per_gas_wei,
        result.max_priority_fee_per_gas_wei,
        result.auto_execute_max_eth,
    )
    assert identities == (
        result.signer_private_key,
        result.api_key,
        result.approver_api_key,
        result.policy_admin_api_key,
        result.database_url,
    )
    assert "http://127.0.0.1:4317" in result.app_cors_origins
    assert "http://127.0.0.1:3000" in result.app_cors_origins
    assert result.invoice_inbox == str(tmp_path / "persistent-inbox")
    assert result.invoice_search_roots == [str(tmp_path / "approved-documents")]
    assert (tmp_path / "persistent-inbox").is_dir()
    assert preparation_settings(result).invoice_inbox == result.invoice_inbox


def test_preparation_rejects_simulation_and_wrong_chain():
    settings = deepcopy(get_settings())
    with pytest.raises(ValueError):
        preparation_settings(settings)
    settings.execution_mode = "sepolia"
    settings.chain_id = 1
    with pytest.raises(ValueError):
        preparation_settings(settings)
