from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Meter:
    kind: str  # 'electricity' or 'gas'
    mpan_or_mprn: str
    serial: str
    tariff_code: Optional[str] = None  # optional override

@dataclass
class OctopusSettings:
    """Configuration specific to Octopus Energy API client."""
    octopus_api_key: str
    account_number: str
    meters: List[Meter] = None
    electricity_product_code: Optional[str] = None
    gas_product_code: Optional[str] = None
    electricity_tariff_code: Optional[str] = None
    gas_tariff_code: Optional[str] = None
    bootstrap_lookback_days: int = 30  # default history to pull when no state present

    @staticmethod
    def from_env() -> 'OctopusSettings':
        """Create Octopus settings from environment variables."""
        api_key = os.environ['OCTOPUS_API_KEY']
        account = os.environ['OCTOPUS_ACCOUNT_NUMBER']
        meters_json = os.environ.get('METERS_JSON')
        meters: List[Meter] = []
        if meters_json:
            try:
                parsed = json.loads(meters_json)
            except json.JSONDecodeError:
                # Attempt simple repair for unquoted keys format: [{kind:electricity,...}]
                repaired = meters_json
                # add quotes around keys (basic heuristic)
                import re
                repaired = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', repaired)
                try:
                    parsed = json.loads(repaired)
                except Exception as e:  # noqa: BLE001
                    raise ValueError(
                        f"Malformed METERS_JSON; unable to parse after repair attempt: {e}"
                    )
            for m in parsed:
                meters.append(Meter(**m))
        
        e_product = os.environ.get('ELECTRICITY_PRODUCT_CODE')
        g_product = os.environ.get('GAS_PRODUCT_CODE')
        e_tariff = os.environ.get('ELECTRICITY_TARIFF_CODE')
        g_tariff = os.environ.get('GAS_TARIFF_CODE')
        lookback = int(os.environ.get('BOOTSTRAP_LOOKBACK_DAYS', '30'))
        
        return OctopusSettings(
            octopus_api_key=api_key,
            account_number=account,
            meters=meters,
            electricity_product_code=e_product,
            gas_product_code=g_product,
            electricity_tariff_code=e_tariff,
            gas_tariff_code=g_tariff,
            bootstrap_lookback_days=lookback,
        )

@dataclass
class Settings(OctopusSettings):
    """
    Legacy settings class for backward compatibility.
    Combines Octopus and ADLS settings.
    New code should use OctopusSettings + ADLSConfig separately.
    """
    storage_account_name: str = None
    storage_container_consumption: str = 'consumption'
    storage_container_curated: str = 'curated'

    @staticmethod
    def from_env() -> 'Settings':
        """Create legacy combined settings from environment variables."""
        # Get Octopus settings
        octopus_settings = OctopusSettings.from_env()
        
        # Get ADLS settings
        storage = os.environ['STORAGE_ACCOUNT_NAME']
        consumption_container = os.environ.get('STORAGE_CONTAINER_CONSUMPTION', 'consumption')
        curated_container = os.environ.get('STORAGE_CONTAINER_CURATED', 'curated')
        
        # Create combined settings object
        return Settings(
            octopus_api_key=octopus_settings.octopus_api_key,
            account_number=octopus_settings.account_number,
            meters=octopus_settings.meters,
            electricity_product_code=octopus_settings.electricity_product_code,
            gas_product_code=octopus_settings.gas_product_code,
            electricity_tariff_code=octopus_settings.electricity_tariff_code,
            gas_tariff_code=octopus_settings.gas_tariff_code,
            bootstrap_lookback_days=octopus_settings.bootstrap_lookback_days,
            storage_account_name=storage,
            storage_container_consumption=consumption_container,
            storage_container_curated=curated_container,
        )
