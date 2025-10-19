"""Unified Tado backfill script: single dayReport fetch per device/day parsing both demand and temperature.

Usage (example):
    python scripts/backfill_tado_unified.py --start 2024-09-11 --end 2024-09-13

Writes daily parquet files into two folders (demand, temps) under the configured ADLS container path.
Keeps existing separation; could be unified later.
"""
from __future__ import annotations
import argparse
import os
import datetime as dt
import pandas as pd
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

import logging
from tadoclient.client import TadoClient
from tadoclient.config import TadoSettings
from adlsclient.writer import DataLakeWriter
from adlsclient.config import ADLSConfig
from dotenv import load_dotenv

logger = logging.getLogger("tado.backfill")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _write_day(date_str: str, demand_events: List[dict], temp_records: List[dict], adls_writer: DataLakeWriter | None, args):
    """Write one day's demand & temperature events locally (and to ADLS if enabled)."""
    if args.dry_run:
        return
    # Demand
    if demand_events:
        df_d = pd.DataFrame(demand_events)
        for trv_id, g in df_d.groupby('trv_id'):
            if not getattr(args, 'adls_only', False):  # only write local if not ADLS-only
                folder_path = os.path.join(args.out, 'heating', trv_id, f'date={date_str}')
                ensure_dir(folder_path)
                g.to_parquet(os.path.join(folder_path, 'demand.parquet'), index=False)
            if adls_writer:
                adls_writer.write_demand_events(trv_id, g.to_dict('records'))
    # Temperature
    if temp_records:
        df_t = pd.DataFrame(temp_records)
        for device_id, g in df_t.groupby('device_id'):
            if not getattr(args, 'adls_only', False):
                folder_path = os.path.join(args.out, 'heating', device_id, f'date={date_str}')
                ensure_dir(folder_path)
                g.to_parquet(os.path.join(folder_path, 'temperature.parquet'), index=False)
            if adls_writer:
                adls_writer.write_temperature_events(device_id, g.to_dict('records'))
    # Unified optional (skip when ADLS-only because local file is the objective there)
    if args.unified and (demand_events or temp_records) and not getattr(args, 'adls_only', False):
        combined = []
        combined.extend([{"record_kind": "demand", **e} for e in demand_events])
        combined.extend([{"record_kind": "temperature", **t} for t in temp_records])
        if combined:
            df_u = pd.DataFrame(combined)
            folder_path = os.path.join(args.out, 'heating_unified', f'date={date_str}')
            ensure_dir(folder_path)
            df_u.to_parquet(os.path.join(folder_path, 'unified.parquet'), index=False)



def fetch_device_day_report(client: TadoClient, device, date_str: str):
    """Fetch dayReport for a single device and date. Returns (date_str, device, day_json) or None on error."""
    try:
        day_json = client.get_day_report(device, date_str)
        return date_str, device, day_json
    except Exception as e:
        logger.warning(f"Failed dayReport fetch for zone {device.zone_id} on {date_str}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD) inclusive')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD) inclusive')
    parser.add_argument('--out', default='data', help='Local output base path (default: data)')
    parser.add_argument('--dry-run', action='store_true', help='Fetch and parse but do not write parquet files')
    parser.add_argument('--key-vault', help='Key Vault name for token auth (overrides KEY_VAULT_NAME env)')
    parser.add_argument('--unified', action='store_true', help='Also emit a single unified parquet per day (heating_unified/date.parquet)')
    parser.add_argument('--mock', action='store_true', help='Mock mode: generate synthetic data without hitting Tado API')
    parser.add_argument('--max-workers', type=int, default=7, help='Maximum number of concurrent API requests per day (default: 7, matches typical zone count)')
    parser.add_argument('--local-only', action='store_true', help='Write only to local files, skip ADLS upload (default: write to both)')
    parser.add_argument('--adls-only', action='store_true', help='Write only to ADLS (no local parquet files will be created)')
    args = parser.parse_args()

    # Load environment (.env) so required variables like TADO_HOME_ID are present
    if os.path.exists('.env'):
        load_dotenv('.env')
    start = dt.datetime.fromisoformat(args.start)
    end = dt.datetime.fromisoformat(args.end)

    # Validate mutually exclusive flags
    if args.local_only and args.adls_only:
        logger.error('Cannot use --local-only and --adls-only together.')
        return 2

    settings = TadoSettings.from_env()
    client = TadoClient(settings)
    
    # Initialize ADLS writer if not local-only mode
    adls_writer = None
    if not args.local_only and not args.mock:
        try:
            adls_config = ADLSConfig.from_env()
            adls_writer = DataLakeWriter(adls_config)
            logger.info("✅ ADLS writer initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize ADLS writer: {e}")
            logger.warning("Will write to local files only")
    elif args.local_only:
        logger.info("📁 Local-only mode - writing to local files only")
    elif args.adls_only:
        logger.info("☁️ ADLS-only mode - writing only to ADLS (no local parquet)")
    else:
        logger.info("🎭 Mock mode - no ADLS upload needed")

    if args.mock:
        logger.warning("Running in MOCK mode – no live API calls will be made.")
    else:
        # Authenticate (non-interactive via Key Vault if provided)
        kv = args.key_vault or os.environ.get('KEY_VAULT_NAME')
        if kv:
            try:
                client.authenticate_from_key_vault(kv)
            except Exception as e:
                logger.error(f"Key Vault authentication failed: {e}")
                return 1
        else:
            logger.info("No Key Vault provided; attempting interactive authenticate()")
            client.authenticate()

    # STREAMING MODE: process and write each day immediately
    demand_day_count = 0
    temp_day_count = 0

    if args.mock:
        cur = start.date()
        while cur <= end.date():
            date_str = cur.isoformat()
            demand_events = [
                {"trv_id": "mock1", "zone_id": "1", "requested": True, "heat_demand": "LOW", "timestamp": f"{date_str}T06:00:00Z", "duration_minutes": 30},
                {"trv_id": "mock1", "zone_id": "1", "requested": True, "heat_demand": "HIGH", "timestamp": f"{date_str}T07:00:00Z", "duration_minutes": 15},
            ]
            temp_records = [
                {"device_id": "mock1", "zone_id": "1", "temperature": 19.2, "timestamp": f"{date_str}T06:00:00Z", "sensor_type": "inside"},
                {"device_id": "mock1", "zone_id": "1", "temperature": 21.0, "timestamp": f"{date_str}T07:00:00Z", "sensor_type": "target"},
            ]
            _write_day(date_str, demand_events, temp_records, adls_writer, args)
            if demand_events:
                demand_day_count += 1
            if temp_records:
                temp_day_count += 1
            cur += dt.timedelta(days=1)
    else:
        devices = [d for d in client.enumerate_devices() if d.device_type == 'trv']
        logger.info(f"Streaming fetch/write for {len(devices)} devices with {args.max_workers} concurrent requests per day")
        current_date = start.date()
        end_date = end.date()
        import time
        while current_date <= end_date:
            date_str = current_date.isoformat()
            day_start = time.time()
            with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
                future_to_device = {
                    executor.submit(fetch_device_day_report, client, device, date_str): device
                    for device in devices
                }
                all_demand = []
                all_temps = []
                success = 0
                for future in as_completed(future_to_device):
                    result = future.result()
                    if result:
                        _, device, day_json = result
                        demand_events, temp_records = client.parse_day_report(device, day_json)
                        all_demand.extend(demand_events)
                        all_temps.extend(temp_records)
                        success += 1
            elapsed = time.time() - day_start
            logger.info(f"Day {date_str} complete: {success}/{len(devices)} zones in {elapsed:.1f}s; writing immediately...")
            _write_day(date_str, all_demand, all_temps, adls_writer, args)
            if all_demand:
                demand_day_count += 1
            if all_temps:
                temp_day_count += 1
            current_date += dt.timedelta(days=1)

    logger.info('Streaming backfill complete:')
    logger.info(f"  Demand days written: {demand_day_count}")
    logger.info(f"  Temp days written:   {temp_day_count}")
    if args.adls_only:
        logger.info('Mode: ADLS-only (no local parquet).')
    elif args.local_only:
        logger.info('Mode: Local-only (no ADLS uploads).')
    else:
        logger.info('Mode: Dual local + ADLS.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
