"""
Legacy module for backward compatibility.
Storage operations have moved to adlsclient package.
This module provides compatibility wrappers.
"""
from __future__ import annotations

# Import shared ADLS components
from adlsclient.config import ADLSConfig
from adlsclient.state import StateStore as BaseStateStore
from adlsclient.writer import DataLakeWriter as BaseDataLakeWriter

from .config import OctopusSettings


class DataLakeWriter(BaseDataLakeWriter):
    """
    Legacy compatibility wrapper for DataLakeWriter.
    New code should use adlsclient.writer.DataLakeWriter directly.
    """
    
    def __init__(self, settings: OctopusSettings):
        # Convert octopus settings to ADLS config
        adls_config = ADLSConfig(
            storage_account_name=settings.storage_account_name,
            storage_container_consumption=settings.storage_container_consumption,
            storage_container_curated=settings.storage_container_curated,
        )
        super().__init__(adls_config)
        self.settings = settings

class StateStore:
    """
    Legacy compatibility wrapper for StateStore.
    New code should use adlsclient.state.StateStore directly.
    """
    
    def __init__(self, settings: OctopusSettings, service_client):
        """Legacy wrapper initialiser.

        In production we delegate to BaseStateStore (blob backed). For tests the
        dummy service implements get_blob_client returning a simple object with
        download_blob/upload_blob. That still works with BaseStateStore so we
        can reuse it. Keep thin wrapper.
        """
        self._state_store = BaseStateStore(settings.storage_container_consumption, service_client)
    
    def get_last_interval(self, mpan_mprn: str, serial: str):
        key = f"{mpan_mprn}:{serial}"
        return self._state_store.get_last_interval(key)
    
    def set_last_interval(self, mpan_mprn: str, serial: str, interval_end):
        key = f"{mpan_mprn}:{serial}"
        return self._state_store.set_last_interval(key, interval_end)
