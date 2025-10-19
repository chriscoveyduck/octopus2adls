import azure.functions as func
import logging
import datetime as dt
import json
import os
import sys

# Ensure src package path precedes functions duplicates
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# Import from new modular packages
from octopusclient.config import Settings
from octopusclient.client import OctopusClient
from octopusclient.storage import DataLakeWriter, StateStore

def main(myTimer: func.TimerRequest) -> None:
    """
    Timer-triggered scheduler function that orchestrates data ingestion from multiple sources.
    Currently supports Octopus Energy data; extensible for Tado, Weather, etc.
    """
    if myTimer.past_due:
        logging.warning('The timer is past due!')

    utc_timestamp = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()
    logging.info(f'Data ingestion scheduler triggered at: {utc_timestamp}')
    
    # Track overall results across all data sources
    total_success = 0
    total_errors = 0
    
    # Process Octopus Energy data (optional skip via SKIP_OCTOPUS=1)
    if os.environ.get('SKIP_OCTOPUS', '0') == '1':
        logging.info('Skipping Octopus ingestion due to SKIP_OCTOPUS=1')
    else:
        try:
            octopus_success, octopus_errors = run_octopus_ingestion()
            total_success += octopus_success
            total_errors += octopus_errors
        except Exception as e:
            logging.error(f"Fatal error in Octopus ingestion: {str(e)}")
            total_errors += 1
    
    # Process Tado demand data (optional skip via SKIP_TADO=1)
    if os.environ.get('SKIP_TADO', '0') == '1':
        logging.info('Skipping Tado ingestion due to SKIP_TADO=1')
    else:
        try:
            tado_success, tado_errors = run_tado_ingestion()
            total_success += tado_success
            total_errors += tado_errors
        except Exception as e:
            logging.error(f"Fatal error in Tado ingestion: {str(e)}")
            total_errors += 1
    
    # TODO: Add Weather ingestion when weatherclient is implemented
        
    logging.info(
        f"Scheduler completed: {total_success} sources succeeded, "
        f"{total_errors} sources failed"
    )
    
    if total_errors > 0 and total_success == 0:
        # All sources failed - mark function execution as failed
        raise Exception(f"All data ingestion sources failed ({total_errors} errors)")

def run_octopus_ingestion() -> tuple[int, int]:
    """Run Octopus Energy data ingestion. Returns (success_count, error_count)."""
    logging.info("Starting Octopus Energy ingestion")
    
    # Load settings from environment
    settings = Settings.from_env()
    
    # Initialize clients
    client = OctopusClient(settings.octopus_api_key, settings.account_number)
    writer = DataLakeWriter(settings)
    
    # Process each meter
    success_count = 0
    error_count = 0
    
    for meter in settings.meters:
        try:
            logging.info(f"Processing meter: {meter.kind} {meter.mpan_or_mprn} ({meter.serial})")
            
            # Run incremental ingestion (fetches only new data since last run)
            records_processed = ingest_meter_consumption(client, writer, meter, settings)
            
            logging.info(
                f"Successfully processed {records_processed} records for meter "
                f"{meter.mpan_or_mprn}"
            )
            success_count += 1
            
        except Exception as e:
            logging.error(f"Failed to process meter {meter.mpan_or_mprn}: {str(e)}")
            error_count += 1
            # Continue processing other meters even if one fails
            
    logging.info(
        f"Octopus ingestion completed: {success_count} meters succeeded, "
        f"{error_count} meters failed"
    )
    return success_count, error_count

def ingest_meter_consumption(client: OctopusClient, writer: DataLakeWriter, meter, settings: Settings) -> int:
    """Incremental ingestion for a single meter."""
    state_store = StateStore(settings, writer.service_client)
    
    # Get the last processed interval
    last_interval = state_store.get_last_interval(meter.mpan_or_mprn, meter.serial)

    # Calculate time window for incremental fetch (use overlap strategy)
    # We historically stored interval_end; we now store interval_start. To remain
    # backward compatible and avoid missing the next interval (DST edge cases),
    # we always overlap by 30 minutes when resuming.
    now = dt.datetime.now(dt.timezone.utc)
    if last_interval:
        # Overlap by one half-hour interval; subtract 30 minutes (plus a 1s epsilon) to ensure inclusivity
        overlap_start = last_interval - dt.timedelta(minutes=30, seconds=1)
        # Guard against going before a sensible minimum (e.g., 2015 earliest data)
        earliest_allowed = dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc)
        if overlap_start < earliest_allowed:
            overlap_start = earliest_allowed
        start_time = overlap_start
        logging.info(
            f"Resuming from stored interval {last_interval} with overlap. "
            f"Query start={start_time}"
        )
    else:
        # First run - fetch last 7 days (could be adjusted to discover true earliest)
        start_time = now - dt.timedelta(days=7)
        logging.info(
            f"First run - fetching last 7 days from {start_time}"
        )
    
    # Fetch consumption data
    consumption_records = client.get_consumption(meter, start_time, now)
    logging.info(
        f"Fetched {len(consumption_records)} consumption records"
    )
    
    if not consumption_records:
        logging.info("No new consumption data")
        return 0
    
    # Write consumption data
    writer.write_consumption(meter, consumption_records)
    
    # Update state with the latest INTERVAL START (new semantics)
    if consumption_records:
        def _parse(ts: str) -> dt.datetime:
            # Accept either Z or offset, normalize to UTC
            ts_norm = ts.replace('Z', '+00:00')
            dt_obj = dt.datetime.fromisoformat(ts_norm)
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
            else:
                dt_obj = dt_obj.astimezone(dt.timezone.utc)
            return dt_obj
        latest_record = max(consumption_records, key=lambda r: r['interval_start'])
        latest_start = _parse(latest_record['interval_start'])
        state_store.set_last_interval(meter.mpan_or_mprn, meter.serial, latest_start)
        logging.info(
            f"Updated last interval (stored as latest interval_start) to: {latest_start}"
        )
    
    return len(consumption_records)

def run_tado_ingestion() -> tuple[int, int]:
    """Run unified Tado heating ingestion (demand + temps) writing to 'heating' container."""
    logging.info("Starting Tado heating ingestion (unified)")
    from tadoclient.config import TadoSettings
    from tadoclient.client import TadoClient
    from adlsclient.writer import DataLakeWriter
    from adlsclient.config import ADLSConfig
    from tadoclient.state import TadoStateStore

    try:
        tado_settings = TadoSettings.from_env()
    except Exception as e:
        logging.error(f"Failed to load Tado settings: {e}")
        return 0, 1

    tado_client = TadoClient(tado_settings)
    key_vault_name = os.environ.get('KEY_VAULT_NAME', 'energyanalyticsdev01kv')
    tado_client.authenticate_from_key_vault(key_vault_name)

    adls_config = ADLSConfig.from_env()
    writer = DataLakeWriter(adls_config)
    state = TadoStateStore('heating', writer.service_client)

    devices = [d for d in tado_client.enumerate_devices() if d.device_type == 'trv']
    if not devices:
        logging.info("No TRV devices discovered; skipping")
        return 0, 0

    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    # Determine per-device last processed date (day-level) based on latest demand event timestamp stored in state
    # We store state per (device_id, zone_id) using last interval semantics
    per_device_start: dict[str, dt.datetime] = {}
    earliest = now
    default_lookback = dt.timedelta(hours=1)
    for d in devices:
        last = state.get_last_interval(d.device_id, d.zone_id)
        if last:
            # Resume from last timestamp truncated to date (to ensure we don't miss tail of that day)
            start = last.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now - default_lookback
        per_device_start[d.device_id] = start
        if start < earliest:
            earliest = start

    # Iterate days from earliest to now (inclusive) per device with single dayReport fetch each
    success = 0
    errors = 0
    day_cursor = earliest.date()
    end_date = now.date()
    while day_cursor <= end_date:
        date_str = day_cursor.isoformat()
        for device in devices:
            # Skip if this day is before device start window
            if day_cursor < per_device_start[device.device_id].date():
                continue
            try:
                report = tado_client.get_day_report(device, date_str)
                demand_events, temp_records = tado_client.parse_day_report(device, report)
                # Filter out events that are not newer than state last interval (for partial first day) 
                last_processed = state.get_last_interval(device.device_id, device.zone_id)
                if last_processed:
                    demand_events = [e for e in demand_events if dt.datetime.fromisoformat(e['timestamp'].replace('Z','+00:00')) > last_processed]
                    temp_records = [e for e in temp_records if dt.datetime.fromisoformat(e['timestamp'].replace('Z','+00:00')) > last_processed]
                if demand_events:
                    writer.write_demand_events(device.device_id, demand_events)
                if temp_records:
                    writer.write_temperature_events(device.device_id, temp_records)
                # Advance state with max of any timestamps we wrote
                all_ts = []
                for coll in (demand_events, temp_records):
                    for rec in coll:
                        try:
                            all_ts.append(dt.datetime.fromisoformat(rec['timestamp'].replace('Z','+00:00')))
                        except Exception:
                            pass
                if all_ts:
                    latest_ts = max(all_ts)
                    state.set_last_interval(device.device_id, device.zone_id, latest_ts)
                logging.info(
                    f"Heating day {date_str} TRV {device.device_id}: "
                    f"demand={len(demand_events)} temps={len(temp_records)}"
                )
                success += 1
            except Exception as e:
                logging.error(
                    f"Failed heating ingestion for TRV {device.device_id} on {date_str}: {e}"
                )
                errors += 1
        day_cursor += dt.timedelta(days=1)

    logging.info(
        f"Tado heating ingestion completed: {success} device-day successes, "
        f"{errors} failures"
    )
    return success, errors