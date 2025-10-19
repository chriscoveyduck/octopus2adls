import pandas as pd

 # ...existing code...
from octopus2adls.storage import DataLakeWriter


class DummyWriter(DataLakeWriter):
    def __init__(self, settings):
        self.settings = settings
        self.service_client = type('x', (), {})()
        self.raw_container = 'raw'
    def _write_parquet(self, path, df):
        pass


def test_rate_match_cost():
    # ...existing code...
    # ...existing code...
    # ...existing code...
    consumption = [
        {
            "interval_start": "2024-01-01T00:00:00Z",
            "interval_end": "2024-01-01T00:30:00Z",
            "consumption": 0.5
        },
        {
            "interval_start": "2024-01-01T00:30:00Z",
            "interval_end": "2024-01-01T01:00:00Z",
            "consumption": 0.7
        },
    ]
    rates = [
        {
            "valid_from": "2023-12-31T23:30:00Z",
            "valid_to": "2024-01-01T00:30:00Z",
            "value_inc_vat": 0.30
        },
        {"valid_from": "2024-01-01T00:30:00Z", "valid_to": None, "value_inc_vat": 0.28},
    ]
    # emulate join logic
    df_c = pd.DataFrame(consumption)
    df_c['interval_start'] = pd.to_datetime(df_c['interval_start'], utc=True)
    df_c['interval_end'] = pd.to_datetime(df_c['interval_end'], utc=True)
    df_r = pd.DataFrame(rates)
    df_r['valid_from'] = pd.to_datetime(df_r['valid_from'], utc=True)
    df_r['valid_to'] = pd.to_datetime(df_r['valid_to'], utc=True)
    costs = []
    for _, crow in df_c.iterrows():
        for _, rrow in df_r.iterrows():
            if (
                crow['interval_start'] >= rrow['valid_from'] and
                (pd.isna(rrow['valid_to']) or crow['interval_start'] < rrow['valid_to'])
            ):
                costs.append(crow['consumption'] * rrow['value_inc_vat'])
    assert round(sum(costs), 4) == round(0.5*0.30 + 0.7*0.28, 4)
