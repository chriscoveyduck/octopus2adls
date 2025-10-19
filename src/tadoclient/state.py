from __future__ import annotations

import datetime as dt

from adlsclient.state import StateStore as BaseStateStore


class TadoStateStore:
    """Specialized state store for Tado devices keyed by device_id:zone_id."""

    def __init__(self, container_name: str, service_client):
        self._base = BaseStateStore(container_name, service_client)

    @staticmethod
    def _key(device_id: str, zone_id: str) -> str:
        return f"{device_id}:{zone_id}"

    def get_last_interval(self, device_id: str, zone_id: str) -> dt.datetime | None:
        return self._base.get_last_interval(self._key(device_id, zone_id))

    def set_last_interval(self, device_id: str, zone_id: str, interval_end: dt.datetime):
        return self._base.set_last_interval(self._key(device_id, zone_id), interval_end)
