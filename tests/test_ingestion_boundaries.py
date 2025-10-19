import datetime as dt
import pytest
from octopus2adls.config import Meter, Settings
from octopus2adls.storage import StateStore, DataLakeWriter

class DummyService:
    def __init__(self):
        self.state = {}
    def get_blob_client(self, container, blob):
        class Blob:
            def __init__(self, state):
                self.state = state
            def download_blob(self):
                class R:
                    def readall(inner_self):
                        import json
                        return json.dumps(self.state)
                return R()
            def upload_blob(self, data, overwrite=False):
                import json
                self.state.update(json.loads(data))
        return Blob(self.state)

class DummyWriter(DataLakeWriter):
    def __init__(self, settings):
        self.settings = settings
        self.service_client = DummyService()
        self.raw_container = 'raw'
    def _write_parquet(self, path, df):
        pass

def test_overlap_boundary():
    # Simulate state and overlap logic
    settings = Settings(octopus_api_key='x', account_number='a', storage_account_name='acc', meters=[])
    writer = DummyWriter(settings)
    store = StateStore(settings, writer.service_client)
    meter = Meter(kind='gas', mpan_or_mprn='701337809', serial='E6E07565322221')
    # Set last interval to a known value
    last = dt.datetime(2025, 10, 16, 23, 30, tzinfo=dt.timezone.utc)
    store.set_last_interval(meter.mpan_or_mprn, meter.serial, last)
    # Overlap calculation (should subtract 30m + 1s)
    overlap_start = last - dt.timedelta(minutes=30, seconds=1)
    assert overlap_start == dt.datetime(2025, 10, 16, 22, 59, 59, tzinfo=dt.timezone.utc)

def test_dst_transition():
    # Simulate DST boundary
    settings = Settings(octopus_api_key='x', account_number='a', storage_account_name='acc', meters=[])
    writer = DummyWriter(settings)
    store = StateStore(settings, writer.service_client)
    meter = Meter(kind='electricity', mpan_or_mprn='1900021218905', serial='19L3269639')
    # Set last interval to DST change
    last = dt.datetime(2025, 3, 30, 1, 30, tzinfo=dt.timezone.utc)  # DST start in UK
    store.set_last_interval(meter.mpan_or_mprn, meter.serial, last)
    overlap_start = last - dt.timedelta(minutes=30, seconds=1)
    assert overlap_start == dt.datetime(2025, 3, 30, 0, 59, 59, tzinfo=dt.timezone.utc)

def test_state_advancement():
    # Simulate state advancement
    settings = Settings(octopus_api_key='x', account_number='a', storage_account_name='acc', meters=[])
    writer = DummyWriter(settings)
    store = StateStore(settings, writer.service_client)
    meter = Meter(kind='electricity', mpan_or_mprn='1900021218905', serial='19L3269639')
    # Initial state
    assert store.get_last_interval(meter.mpan_or_mprn, meter.serial) is None
    ts = dt.datetime(2025, 10, 17, 23, 30, tzinfo=dt.timezone.utc)
    store.set_last_interval(meter.mpan_or_mprn, meter.serial, ts)
    got = store.get_last_interval(meter.mpan_or_mprn, meter.serial)
    assert got == ts
