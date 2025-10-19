from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TadoDevice:
    """Configuration for a Tado device (thermostat, radiator valve, etc.)."""
    device_id: str
    name: str
    device_type: str  # 'thermostat', 'radiator_valve', etc.
    zone_id: Optional[str] = None

@dataclass
class TadoSettings:
    """Configuration for Tado API client."""
    home_id: str
    devices: List[TadoDevice] = None

    @staticmethod
    def from_env() -> 'TadoSettings':
        import json
        home_id = os.environ['TADO_HOME_ID']
        devices_json = os.environ.get('TADO_DEVICES_JSON')
        devices = []
        if devices_json:
            try:
                parsed = json.loads(devices_json)
                for d in parsed:
                    devices.append(TadoDevice(**d))
            except Exception as e:
                raise ValueError(f"Malformed TADO_DEVICES_JSON: {e}")
        return TadoSettings(
            home_id=home_id,
            devices=devices,
        )