from octopus2adls.config import Meter, Settings
from octopus2adls.storage import DataLakeWriter

class DummySettings(Settings):
    pass

def test_partition_path_building(monkeypatch):
    settings = Settings(
        octopus_api_key='x',
        account_number='a',
        storage_account_name='acc',
        meters=[]
    )
    writer = DataLakeWriter(settings)
    # monkeypatch the upload to avoid Azure call
    monkeypatch.setattr(writer, '_write_parquet', lambda path, df: path)
    meter = Meter(kind='electricity', mpan_or_mprn='123', serial='ABC')
    records = [
        {"interval_end": "2024-01-01T01:00:00Z", "consumption": 1.0},
        {"interval_end": "2024-01-01T02:00:00Z", "consumption": 2.0},
        {"interval_end": "2024-01-02T01:00:00Z", "consumption": 3.0},
    ]
    writer.write_consumption(meter, records)
