from __future__ import annotations
import datetime as dt
from typing import Dict, List, Any, Optional, Tuple
import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import Meter

BASE_URL = "https://api.octopus.energy/v1"  # official base

class OctopusError(Exception):
    pass

class OctopusClient:
    def __init__(self, api_key: str, account_number: str):
        self.api_key = api_key
        self.account_number = account_number
        # follow_redirects handles any 301/302 from API (some endpoints may redirect)
        self._client = httpx.Client(timeout=30.0, auth=(api_key, ''), follow_redirects=True)
        self._log = logging.getLogger(__name__)

    # ---------------- Internal Helpers -----------------
    @staticmethod
    def _fmt(ts: dt.datetime) -> str:
        """Format datetime to Octopus API expected UTC Zulu string."""
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        else:
            ts = ts.astimezone(dt.timezone.utc)
        return ts.strftime('%Y-%m-%dT%H:%M:%SZ')

    @retry(reraise=True, stop=stop_after_attempt(5), wait=wait_exponential(multiplier=0.5, max=10), retry=retry_if_exception_type(httpx.HTTPError))
    def _get(self, path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        resp = self._client.get(url, params=params)
        if resp.status_code >= 400:
            raise OctopusError(f"Error {resp.status_code}: {resp.text}")
        # Defensive: some unexpected redirects or empty bodies could return non-JSON
        content_bytes = getattr(resp, "content", None)
        if content_bytes is None:
            # Fallback to text attribute if custom test double omits .content
            if not getattr(resp, "text", ""):
                raise OctopusError(f"Empty response body for {url}")
        else:
            if not content_bytes:
                raise OctopusError(f"Empty response body for {url}")
        try:
            return resp.json()
        except ValueError as e:  # JSON decode error
            raise OctopusError(f"Non-JSON response for {url}: {resp.text[:200]}") from e

    def _paginate(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        page = 1
        while True:
            page_params = dict(params)
            page_params['page'] = page
            data = self._get(path, page_params)
            objs = data.get('results', [])
            results.extend(objs)
            # Debug log page progress (helps validate page_size effectiveness & redirect removal)
            if page == 1 or page % 25 == 0:
                self._log.debug("Fetched page %s (%s cumulative records) for %s", page, len(results), path)
            if not data.get('next'):
                break
            page += 1
        return results

    def get_consumption(self, meter: Meter, start: dt.datetime, end: dt.datetime) -> List[Dict[str, Any]]:
        # API uses UTC ISO format with trailing 'Z' (no offset like +00:00)
        base_path = f"/electricity-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption" if meter.kind == 'electricity' else f"/gas-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption"
        path = base_path if base_path.endswith('/') else base_path + '/'
        params = {
            'period_from': self._fmt(start),
            'period_to': self._fmt(end),
            'order_by': 'period',  # ascending so earliest first (stable ordering)
            'page_size': 250,
        }
        return self._paginate(path, params)

    def get_unit_rates(self, product_code: str, tariff_code: str, start: dt.datetime, end: dt.datetime) -> List[Dict[str, Any]]:
        """Retrieve standard unit rates for given product+tariff within window."""
        base_path = f"/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates" if tariff_code.startswith('E-') or '-E-' in tariff_code else f"/products/{product_code}/gas-tariffs/{tariff_code}/standard-unit-rates"
        path = base_path if base_path.endswith('/') else base_path + '/'
        params = {
            'period_from': self._fmt(start),
            'period_to': self._fmt(end),
            'order_by': 'period',
            'page_size': 250,
        }
        return self._paginate(path, params)

    # ---------------- Availability Helpers -----------------
    def get_earliest_interval(self, meter: Meter) -> Dict[str, Any] | None:
        """Return earliest interval.

        NOTE: Octopus API returns newest-first by default when order_by not specified (documented behavior varies).
        To robustly obtain earliest we request explicit ascending order and walk pages until no next link.
        This can be expensive for multi-year data; callers can implement caching.
        """
        path = f"/electricity-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption" if meter.kind == 'electricity' else f"/gas-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption"
        # Ascending order
        params = { 'order_by': 'period', 'page': 1 }
        data = self._get(path, params)
        earliest: Dict[str, Any] | None = None
        while True:
            results = data.get('results', [])
            if not results:
                break
            # First page first record is earliest so far (ascending order)
            if earliest is None:
                earliest = results[0]
            # If there's a next page, fetch it; we still keep earliest from first page only.
            next_url = data.get('next')
            if not next_url:
                break
            # Extract page parameter for next page if present
            # Simpler: follow absolute URL
            resp = self._client.get(next_url)
            if resp.status_code >= 400:
                break
            data = resp.json()
        return earliest

    def get_latest_interval(self, meter: Meter) -> Dict[str, Any] | None:
        """Return most recent interval (cheap single page)."""
        path = f"/electricity-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption" if meter.kind == 'electricity' else f"/gas-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption"
        params = { 'order_by': '-period', 'page_size': 1 }
        data = self._get(path, params)
        results = data.get('results', [])
        return results[0] if results else None

    def find_earliest_interval_deep(self, meter: Meter, baseline_start: dt.datetime | None = None) -> Dict[str, Any] | None:
        """Return earliest interval by issuing a single wide query.

        The Octopus API defaults to only the last 7 days if period_from/period_to omitted.
        To discover true earliest we supply a far-earlier period_from (baseline) and set ascending order.
        baseline_start: earliest date to attempt (default 2015-01-01 UTC).
        """
        if baseline_start is None:
            baseline_start = dt.datetime(2015, 1, 1, tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        path = f"/electricity-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption" if meter.kind == 'electricity' else f"/gas-meter-points/{meter.mpan_or_mprn}/meters/{meter.serial}/consumption"
        params = {
            'period_from': baseline_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'period_to': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'order_by': 'period',
            'page_size': 1
        }
        data = self._get(path, params)
        results = data.get('results', [])
        return results[0] if results else None

    # ---------------- Tariff / Account Discovery -----------------
    def get_account(self) -> Dict[str, Any]:
        """Return full account payload including meter points & agreements."""
        # Ensure trailing slash for consistency (Octopus docs show trailing slash)
        return self._get(f"/accounts/{self.account_number}/")

    @staticmethod
    def parse_tariff_code(tariff_code: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        """Parse a tariff code into (kind, register, product_code, region).

        Empirical pattern examples:
          E-1R-AGILE-24-09-01-A  -> kind=E, register=1R, product_code=AGILE-24-09-01, region=A
          G-1R-GAS-24-09-01-A    -> kind=G, register=1R, product_code=GAS-24-09-01, region=A

        Some tariffs include additional numeric distributor fragments; we conservatively treat the
        last segment of length 1 as region and everything between register & region as product code.
        """
        parts = tariff_code.split('-')
        if len(parts) < 3:
            return (parts[0][0] if parts else '', None, None, None)
        kind = parts[0][0]
        register = parts[1]
        region = parts[-1] if len(parts[-1]) == 1 else None
        core_parts = parts[2:-1] if region else parts[2:]
        product_code = '-'.join(core_parts) if core_parts else None
        return kind, register, product_code, region

    def discover_active_tariffs(self, as_of: Optional[dt.datetime] = None) -> Dict[str, Dict[str, str]]:
        """Discover active product & tariff codes per energy kind at the given time.

        Returns: { 'electricity': {'tariff_code': ..., 'product_code': ...}, 'gas': {...}}
        Chooses agreement with latest valid_from where valid_from <= as_of < valid_to (or open-ended valid_to).
        """
        if as_of is None:
            as_of = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
        acct = self.get_account()
        result: Dict[str, Dict[str, str]] = {}

        def pick(agreements: List[Dict[str, Any]], kind_key: str):
            chosen = None
            chosen_start = None
            for ag in agreements:
                tcode = ag.get('tariff_code') or ag.get('tariff')
                if not tcode:
                    continue
                vf = ag.get('valid_from')
                vt = ag.get('valid_to')
                try:
                    vf_dt = dt.datetime.fromisoformat(vf.replace('Z', '+00:00')) if vf else None
                    vt_dt = dt.datetime.fromisoformat(vt.replace('Z', '+00:00')) if vt else None
                except Exception:  # noqa: BLE001
                    continue
                if vf_dt and vf_dt <= as_of and (vt_dt is None or as_of < vt_dt):
                    if chosen is None or (chosen_start and vf_dt > chosen_start):
                        kind, reg, product_code, region = self.parse_tariff_code(tcode)
                        # If parse failed, skip.
                        if product_code:
                            chosen = {'tariff_code': tcode, 'product_code': product_code}
                            chosen_start = vf_dt
            if chosen:
                result[kind_key] = chosen

        # Electricity
        for emp in acct.get('electricity_meter_points', []):
            pick(emp.get('agreements', []), 'electricity')
            if 'electricity' in result:
                break  # first successful point is enough for global tariff selection
        # Gas
        for gmp in acct.get('gas_meter_points', []):
            pick(gmp.get('agreements', []), 'gas')
            if 'gas' in result:
                break

        return result

    # ---------------- Meter Discovery -----------------
    def list_all_meters(self) -> Dict[str, list[Dict[str, str]]]:
        """Return all meter serials grouped by kind.

        Returns: {'electricity': [{'mpan_mprn': ..., 'serial': ...}, ...], 'gas': [...]}.
        """
        acct = self.get_account()
        out: Dict[str, list[Dict[str, str]]] = {'electricity': [], 'gas': []}
        for emp in acct.get('electricity_meter_points', []):
            mpan = emp.get('mpan') or emp.get('mpan_number') or emp.get('mpan_mprn')
            for m in emp.get('meters', []):
                serial = m.get('serial_number') or m.get('serial')
                if mpan and serial:
                    out['electricity'].append({'mpan_mprn': mpan, 'serial': serial})
        for gmp in acct.get('gas_meter_points', []):
            mprn = gmp.get('mprn') or gmp.get('mpan_mprn') or gmp.get('mprn_number')
            for m in gmp.get('meters', []):
                serial = m.get('serial_number') or m.get('serial')
                if mprn and serial:
                    out['gas'].append({'mpan_mprn': mprn, 'serial': serial})
        return out
