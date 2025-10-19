import datetime as dt
import json
from octopus2adls.config import Settings
from octopus2adls.storage import StateStore

class DummyBlob:
    def __init__(self):
        self.data = b''
    def download_blob(self):
        class R:  # noqa: D401
            def __init__(self, outer):
                self.outer = outer
            def readall(self):
                return self.outer.data
        return R(self)
    def upload_blob(self, data, overwrite=False):
        self.data = data.encode() if isinstance(data, str) else data

class DummyService:
    def __init__(self):
        self.blob = DummyBlob()
    def get_blob_client(self, container, blob):
        return self.blob

def test_state_roundtrip():
    settings = Settings(
        octopus_api_key='x',
        account_number='a',
        storage_account_name='acc',
        meters=[]
    )
    svc = DummyService()
    store = StateStore(settings, svc)
    assert store.get_last_interval('123','ABC') is None
    ts = dt.datetime(2024,1,1,1)
    store.set_last_interval('123','ABC', ts)
    got = store.get_last_interval('123','ABC')
    assert got == ts

def test_half_hour_intervals():
    settings = Settings(
        octopus_api_key='x',
        account_number='a',
        storage_account_name='acc',
        meters=[]
    )
    svc = DummyService()
    store = StateStore(settings, svc)
    first = dt.datetime(2024,1,1,0,30)
    store.set_last_interval('999','HHH', first)
    assert store.get_last_interval('999','HHH') == first
    # next should start from first (exclusive) handled in function logic (not here)
    # but state keeps exact end
    second = dt.datetime(2024,1,1,1,0)
    store.set_last_interval('999','HHH', second)
    assert store.get_last_interval('999','HHH') == second
