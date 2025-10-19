from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ADLSConfig:
    """Configuration for Azure Data Lake Storage operations."""
    storage_account_name: str
    storage_container_consumption: str = 'consumption'
    storage_container_curated: str = 'curated'
    
    @staticmethod
    def from_env() -> 'ADLSConfig':
        """Create configuration from environment variables."""
        storage_account = os.environ['STORAGE_ACCOUNT_NAME']
        consumption_container = os.environ.get('STORAGE_CONTAINER_CONSUMPTION', 'consumption')
        curated_container = os.environ.get('STORAGE_CONTAINER_CURATED', 'curated')
        
        return ADLSConfig(
            storage_account_name=storage_account,
            storage_container_consumption=consumption_container,
            storage_container_curated=curated_container,
        )