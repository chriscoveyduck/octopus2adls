from __future__ import annotations

import datetime as dt
import json

from azure.storage.blob import BlobServiceClient

STATE_BLOB = 'state/last_interval.json'

class StateStore:
    """Manages state persistence for incremental data loading."""
    
    def __init__(self, container_name: str, service_client: BlobServiceClient):
        self.container_name = container_name
        self.client = service_client.get_blob_client(container=container_name, blob=STATE_BLOB)

    def get_last_interval(self, source_key: str) -> dt.datetime | None:
        """
        Get the last processed interval for a given source key.
        
        Args:
            source_key: Unique identifier for the data source (e.g., "mpan:serial" for Octopus)
            
        Returns:
            The last processed interval datetime (UTC) or None if not found
        """
        try:
            data = self.client.download_blob().readall()
            j = json.loads(data)
            val = j.get(source_key)
            if val:
                # Normalize Z to +00:00 and ensure timezone aware UTC
                # ...existing code...
                # crude detection of offset
                has_tz = (
                    ('Z' in val) or ('+' in val[10:]) or ('-' in val[10:])
                )
                norm = val.replace('Z', '+00:00') if 'Z' in val else val
                dt_obj = dt.datetime.fromisoformat(norm)
                if has_tz:
                    # Ensure UTC
                    if dt_obj.tzinfo is None:
                        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
                    else:
                        dt_obj = dt_obj.astimezone(dt.timezone.utc)
                # If no timezone info originally, return naive as stored expectation
                return dt_obj
        except Exception:
            return None
        return None

    def set_last_interval(self, source_key: str, interval_end: dt.datetime | str):
        """
        Store the last processed interval for a given source key.
        
        Args:
            source_key: Unique identifier for the data source
            interval_end: The interval end datetime to store
        """
        try:
            data = self.client.download_blob().readall()
            j = json.loads(data)
        except Exception:
            j = {}
        
        if isinstance(interval_end, str):
            stored = interval_end
        else:
            if interval_end.tzinfo is None:
                stored = interval_end.isoformat()
            else:
                aware = interval_end.astimezone(dt.timezone.utc)
                stored = aware.isoformat().replace('+00:00', 'Z')
        j[source_key] = stored
        self.client.upload_blob(json.dumps(j, indent=2), overwrite=True)