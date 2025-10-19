"""
Backfill Octopus Energy consumption and rates data to ADLS.
Usage: python backfill_octopus.py
"""
import datetime as dt
from octopusclient.config import Settings
from octopusclient.client import OctopusClient
from octopusclient.storage import DataLakeWriter, StateStore

def main():
    settings = Settings.from_env()
    client = OctopusClient(settings.octopus_api_key, settings.account_number)
    writer = DataLakeWriter(settings)
    state = StateStore(settings, writer.service_client)
    period_to = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    for meter in settings.meters:
        # Backfill 30 days by default
        period_from = period_to - dt.timedelta(days=settings.bootstrap_lookback_days)
        print(f"Backfilling Octopus data for meter {meter.mpan_or_mprn} from {period_from} to {period_to}")
        # Fetch and write consumption
        records = client.get_consumption(meter, period_from, period_to)
        writer.write_consumption(meter, records)
        # Fetch and write rates
        rates = client.get_unit_rates(meter, period_from, period_to)
        writer.write_unit_rates(meter.kind == 'electricity', meter.product_code, meter.tariff_code, rates)
        print(f"Done for meter {meter.mpan_or_mprn}")

if __name__ == "__main__":
    main()
