from __future__ import annotations

import io
import os
from typing import Callable, Dict, List

import pandas as pd
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from .config import ADLSConfig
from .state import StateStore


class DataLakeWriter:
    """Generic writer for structured data to Azure Data Lake Storage Gen2."""
    
    def __init__(self, config: ADLSConfig):
        self.config = config
        
        # Initialize blob service client
        conn = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
        if conn:
            self.service_client = BlobServiceClient.from_connection_string(conn)
        else:
            credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            account_url = f"https://{config.storage_account_name}.blob.core.windows.net"
            self.service_client = BlobServiceClient(account_url=account_url, credential=credential)
        
        self.raw_container = config.storage_container_consumption

    def get_state_store(self) -> StateStore:
        """Get a StateStore instance for managing incremental loads."""
        return StateStore(self.raw_container, self.service_client)

    def write_partitioned_data(
        self, 
        records: List[Dict], 
        path_formatter: Callable[[Dict], str],
        partition_column: str = 'date',
        dedup_columns: List[str] = None
    ):
        """
        Write records to partitioned parquet files in ADLS.
        
        Args:
            records: List of dictionaries containing the data
            path_formatter: Function that takes a record dict and returns the blob path
            partition_column: Column to partition data by (default: 'date')
            dedup_columns: Columns to deduplicate on (default: no deduplication)
        """
        if not records:
            return
            
        df = pd.DataFrame(records)
        
        # Apply deduplication if specified
        if dedup_columns:
            # ...existing code...
            df = df.drop_duplicates(subset=dedup_columns)
            # ...existing code...
            # print(f"Deduplicated records ({deduped} remain)")
        
        # Partition by specified column and write each partition
        if partition_column in df.columns:
            for partition_value, group in df.groupby(partition_column):
                # Get path from first record in group (all should have same partition metadata)
                sample_record = group.iloc[0].to_dict()
                path = path_formatter(sample_record)
                self._write_parquet(path, group.drop(columns=[partition_column]))
        else:
            # No partitioning - write all data to single file
            sample_record = df.iloc[0].to_dict()
            path = path_formatter(sample_record)
            self._write_parquet(path, df)

    def _write_parquet(self, path: str, df: pd.DataFrame):
        """Write DataFrame to parquet file in ADLS."""
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        buf.seek(0)
        blob_client = self.service_client.get_blob_client(container=self.raw_container, blob=path)
        blob_client.upload_blob(buf.getvalue(), overwrite=True)

    # Legacy methods for backward compatibility with octopus2adls
    def write_consumption(self, meter, records: List[Dict]):
        """Legacy method - use write_partitioned_data instead."""
        if not records:
            return
        
        # Normalize: ensure ISO timestamps, add meter identifiers, enforce dtypes
        for rec in records:
            rec['mpan_mprn'] = meter.mpan_or_mprn
            rec['serial'] = meter.serial
            rec['kind'] = meter.kind
        
        df = pd.DataFrame(records)
        
        # Parse timestamps for partitioning
        if 'interval_end' in df.columns:
            df['interval_end'] = pd.to_datetime(df['interval_end'], utc=True)
        if 'interval_start' in df.columns:
            df['interval_start'] = pd.to_datetime(df['interval_start'], utc=True)
            
        # De-duplicate intervals
        if {'interval_start','interval_end'}.issubset(df.columns):
            # ...existing code...
            df = df.drop_duplicates(subset=['interval_start','interval_end'])
        else:
            # ...existing code...
            df = df.drop_duplicates()
    # ...existing code...
        
        df['date'] = df['interval_end'].dt.date
        for date, g in df.groupby('date'):
            date_str = date.isoformat()
            # NOTE: historical data used a redundant leading 'consumption/' segment inside the
            # 'consumption' container resulting in paths like consumption/consumption/kind=...
            # New writes omit that extra prefix. Backfill/migration can copy old blobs to the
            # new layout if desired. Old layout remains readable.
            path = (
                f"kind={meter.kind}/mpan_mprn={meter.mpan_or_mprn}/serial={meter.serial}/date={date_str}/data.parquet"
            )
            self._write_parquet(path, g.drop(columns=['date']))

    def write_unit_rates(
        self,
        is_electricity: bool,
        product_code: str,
        tariff_code: str,
        records: List[Dict]
    ):
        """Legacy method - use write_partitioned_data instead."""
        if not records:
            return
        
        for r in records:
            r['product_code'] = product_code
            r['tariff_code'] = tariff_code
            r['energy'] = 'electricity' if is_electricity else 'gas'
        
        df = pd.DataFrame(records)
        for col in ['valid_from', 'valid_to']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True)
        
        # De-duplicate on key columns
        key_cols = [c for c in ['valid_from','valid_to','tariff_code'] if c in df.columns]
        if key_cols:
            df = df.drop_duplicates(subset=key_cols)
        
        # Partition by date (valid_from date) for pruning
        df['date'] = df['valid_from'].dt.date
        for date, g in df.groupby('date'):
            path = (
                f"rates/energy={'electricity' if is_electricity else 'gas'}/product="
                f"{product_code}/tariff={tariff_code}/date={date.isoformat()}/data.parquet"
            )
            self._write_parquet(path, g.drop(columns=['date']))

    def write_costed_consumption(self, meter, df_costed):
        """Legacy method - use write_partitioned_data instead."""
        df = df_costed.copy()
        df['date'] = df['interval_end'].dt.date
        for date, g in df.groupby('date'):
            path = (
                f"consumption_cost/kind={meter.kind}/mpan_mprn={meter.mpan_or_mprn}/serial={meter.serial}/date={date.isoformat()}/data.parquet"
            )
            self._write_parquet(path, g.drop(columns=['date']))

    def write_demand_events(self, trv_id: str, events: List[Dict]):
        """
        Write Tado demand events to ADLS in demand container: trv=X/date=yyyy-mm-dd/data.parquet
        Each event must have a UTC ISO 8601 timestamp.
        """
        import io

        import pandas as pd
        if not events:
            return
        df = pd.DataFrame(events)
        # Parse timestamp for partitioning
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['date'] = df['timestamp'].dt.date
        for date, g in df.groupby('date'):
            date_str = date.isoformat()
            path = f"trv={trv_id}/date={date_str}/data.parquet"
            # Write directly to demand container
            buf = io.BytesIO()
            g.drop(columns=['date']).to_parquet(buf, index=False)
            buf.seek(0)
            blob_client = self.service_client.get_blob_client(container="heating", blob=path)
            blob_client.upload_blob(buf.getvalue(), overwrite=True)

    def write_temperature_events(self, trv_id: str, events: List[Dict]):
        """
        Write Tado temperature events to ADLS in temps container: trv=X/date=yyyy-mm-dd/data.parquet
        Each event must have a UTC ISO 8601 timestamp.
        """
        import io

        import pandas as pd
        if not events:
            return
        df = pd.DataFrame(events)
        # Parse timestamp for partitioning
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        df['date'] = df['timestamp'].dt.date
        for date, g in df.groupby('date'):
            date_str = date.isoformat()
            path = f"trv={trv_id}/date={date_str}/data.parquet"
            # Write directly to temps container
            buf = io.BytesIO()
            g.drop(columns=['date']).to_parquet(buf, index=False)
            buf.seek(0)
            blob_client = self.service_client.get_blob_client(container="heating", blob=path)
            blob_client.upload_blob(buf.getvalue(), overwrite=True)