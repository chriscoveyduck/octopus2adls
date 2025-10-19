import datetime as dt
from octopus2adls.client import OctopusClient
from octopus2adls.config import Meter

class DummyResp:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = str(json_data)
    def json(self):
        return self._json

class DummyHttpClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0
    def get(self, url, params=None):
        self.calls += 1
        return DummyResp(200, self.pages[self.calls-1])

def test_pagination(monkeypatch):
    pages = [
        {"results": [1,2], "next": True},
        {"results": [3], "next": None}
    ]
    c = OctopusClient(api_key='k', account_number='a')
    c._client = DummyHttpClient(pages)  # type: ignore
    meter = Meter(kind='electricity', mpan_or_mprn='123', serial='ABC')
    data = c.get_consumption(meter, dt.datetime(2024,1,1), dt.datetime(2024,1,2))
    assert data == [1,2,3]
