from __future__ import annotations
import datetime as dt
from typing import Dict, List, Any, Tuple, Iterator
import logging
import httpx
import os
import time

from .config import TadoSettings, TadoDevice

class TadoClient:
    def get_day_report(self, device, date_str):
        """
        Fetch the day report for a given device and date (ISO format string, e.g. '2025-10-18').
        Returns the raw JSON response from the Tado API.
        """
        if not self._access_token:
            self.authenticate()
        import httpx
        # device should have home_id and zone_id attributes
        home_id = getattr(device, 'home_id', None) or getattr(self.settings, 'home_id', None)
        zone_id = getattr(device, 'zone_id', None)
        if home_id is None or zone_id is None:
            raise ValueError("Device must have home_id and zone_id")
        url = (
            f"https://my.tado.com/api/v2/homes/{home_id}/zones/{zone_id}/dayReport?date={date_str}"
        )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = httpx.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
    """
    Client for Tado thermostat API.
    Fetches demand generation events: which TRVs are requesting heating at any moment.
    Ensures timestamps are UTC and ISO 8601 for time series analysis.
    """
    
    def __init__(self, settings: TadoSettings):
        self.settings = settings
        self._log = logging.getLogger(__name__)
        self._client = httpx.Client(timeout=30.0)
        self._access_token = None
        self._refresh_token = None
        self._token_acquired_at = None
        self._key_vault_client = None  # Store for token refresh
        self._token_expires_in = 600  # Default 10 minutes, updated from actual response

    def authenticate(self):
        """
        Authenticate with Tado API using Device Code Flow (OAuth 2.0 RFC 8628).
        This is an interactive process that requires user authorization in a browser.
        """
        import httpx
        import time
        
        client_id = "1bb50063-6b0c-4d11-bd99-387f4a91cc46"  # Official tado° client ID
        
        # Step 1: Initiate device code flow
        device_auth_url = "https://login.tado.com/oauth2/device_authorize"
        device_params = {
            "client_id": client_id,
            "scope": "offline_access"  # Request refresh token
        }
        
        resp = httpx.post(device_auth_url, params=device_params)
        resp.raise_for_status()
        device_data = resp.json()
        
        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri_complete"]
        expires_in = device_data["expires_in"]
        interval = device_data["interval"]
        
        print(f"\nTado Authentication Required:")
        print(f"1. Visit: {verification_uri}")
        print(f"2. User code (should auto-fill): {user_code}")
        print(f"3. Log in to your tado° account")
        print(f"4. Waiting for authorization (expires in {expires_in} seconds)...")
        
        # Step 2: Poll for token
        token_url = "https://login.tado.com/oauth2/token"
        token_params = {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
        }
        
        start_time = time.time()
        while time.time() - start_time < expires_in:
            try:
                token_resp = httpx.post(token_url, params=token_params)
                if token_resp.status_code == 200:
                    token_data = token_resp.json()
                    self._access_token = token_data["access_token"]
                    self._refresh_token = token_data.get("refresh_token")
                    self._token_acquired_at = time.time()
                    self._token_expires_in = token_data.get("expires_in", 600)
                    print("Authentication successful!")
                    return
                elif token_resp.status_code == 400:
                    # Still pending authorization
                    time.sleep(interval)
                    continue
                else:
                    token_resp.raise_for_status()
            except Exception as e:
                self._log.error(f"Token polling error: {e}")
                time.sleep(interval)
        
        raise RuntimeError("Tado authentication timed out. Please try again.")

    def authenticate_from_key_vault(self, key_vault_name: str):
        """
        Robust authentication using tokens stored in Azure Key Vault.
        Handles token expiration with multi-layer fallback strategy.
        Use this method in Azure Functions for non-interactive authentication.
        """
        from azure.keyvault.secrets import SecretClient
        from azure.identity import DefaultAzureCredential
        import httpx
        
        key_vault_url = f"https://{key_vault_name}.vault.azure.net/"
        credential = DefaultAzureCredential()
        secret_client = SecretClient(vault_url=key_vault_url, credential=credential)
        self._key_vault_client = secret_client  # Store for later token refresh
        
        # Strategy 1: Try refresh token
        try:
            refresh_token_secret = secret_client.get_secret("tado-refresh-token")
            self._refresh_token = refresh_token_secret.value
            self._log.info("Retrieved refresh token from Key Vault")
            
            # Use refresh token to get new access token with retry
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self._refresh_access_token(secret_client)
                    self._log.info("✅ Successfully authenticated using refresh token")
                    return True
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 400:
                        self._log.warning("❌ Refresh token expired or invalid")
                        break  # Don't retry on 400, move to fallback
                    elif attempt == max_retries - 1:
                        raise e
                    else:
                        self._log.warning(
                            f"Token refresh attempt {attempt + 1} failed: {e}, retrying..."
                        )
                        import time
                        time.sleep(2 ** attempt)  # Exponential backoff
                except Exception as retry_error:
                    if attempt == max_retries - 1:
                        raise retry_error
                    self._log.warning(
                        f"Token refresh attempt {attempt + 1} failed: {retry_error}, retrying..."
                    )
                    import time
                    time.sleep(2 ** attempt)
            
        except Exception as e:
            self._log.warning(f"Refresh token authentication failed: {e}")
        
        # Strategy 2: Alert and provide clear instructions for manual intervention
        error_msg = (
            "🚨 Tado authentication failed - requires manual token refresh.\n"
            "This typically happens when refresh tokens expire (every 30-90 days).\n\n"
            "To fix:\n"
            "1. Run: python scripts/setup_tado_auth.py\n"
            "2. Complete the browser authentication\n"
            "3. New tokens will be stored automatically\n\n"
            "Consider setting up monitoring alerts for this function."
        )
        
        self._log.error(error_msg)
        raise RuntimeError(error_msg)

    def _refresh_access_token(self, secret_client=None):
        """
        Use refresh token to obtain a new access token.
        Updates Key Vault with new refresh token if rotated.
        """
        import httpx
        
        client_id = "1bb50063-6b0c-4d11-bd99-387f4a91cc46"
        token_url = "https://login.tado.com/oauth2/token"
        
        params = {
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        
        resp = httpx.post(token_url, params=params, timeout=30)
        resp.raise_for_status()
        
        token_data = resp.json()
        self._access_token = token_data["access_token"]
        self._token_acquired_at = time.time()  # Track when token was obtained
        
        # Handle refresh token rotation (Tado rotates refresh tokens)
        if "refresh_token" in token_data:
            old_refresh_token = self._refresh_token
            self._refresh_token = token_data["refresh_token"]
            # Update Key Vault with new refresh token if available and changed
            if secret_client and self._refresh_token != old_refresh_token:
                try:
                    secret_client.set_secret("tado-refresh-token", self._refresh_token)
                    self._log.info(
                        f"Updated rotated refresh token in Key Vault: {self._refresh_token}"
                    )
                    # Immediately read back to verify persistence
                    verify_secret = secret_client.get_secret("tado-refresh-token").value
                    if verify_secret == self._refresh_token:
                        self._log.info("Verified refresh token persisted in Key Vault.")
                    else:
                        self._log.error(
                            f"Refresh token mismatch after update! Expected: "
                            f"{self._refresh_token}, "
                            f"Found: {verify_secret}"
                        )
                except Exception as e:
                    self._log.error(f"Failed to update or verify refresh token in Key Vault: {e}")
        
        expires_in = token_data.get("expires_in", 600)
        self._token_expires_in = expires_in
        self._log.info(
            f"New access token obtained, expires in {expires_in} seconds "
            f"({expires_in/60:.1f} minutes)"
        )

    def _ensure_valid_token(self):
        """
        Check if access token needs refresh and refresh it proactively.
    # Refreshes when 80% of token lifetime has elapsed (typically ~8 minutes for 10-minute tokens).
        If refresh token has expired, re-authenticates completely.
        """
        if not self._access_token:
            return  # Will be handled by authenticate() call
            
        if not self._token_acquired_at:
            return  # No timestamp available, let normal auth handle it
            
        time_elapsed = time.time() - self._token_acquired_at
        refresh_threshold = self._token_expires_in * 0.8  # Refresh at 80% of lifetime
        
        if time_elapsed >= refresh_threshold:
            self._log.info(
                f"Proactively refreshing token after {time_elapsed:.1f}s "
                f"(threshold: {refresh_threshold:.1f}s)"
            )
            try:
                if self._key_vault_client:
                    # Always get the latest refresh token from Key Vault before refreshing
                    # This handles token rotation where Tado gives us a new refresh token
                    refresh_token_secret = self._key_vault_client.get_secret("tado-refresh-token")
                    self._refresh_token = refresh_token_secret.value
                    self._refresh_access_token(self._key_vault_client)
                else:
                    # Fallback to manual refresh without Key Vault update
                    self._refresh_access_token()
            except Exception as e:
                self._log.warning(f"Proactive token refresh failed: {e}")
                # Continue with existing token - will fail on next API call if truly expired

    def get_homes(self) -> list:
        """
        Fetch all homes associated with the authenticated account.
        Returns a list of homes with their IDs and names.
        """
        if not self._access_token:
            self.authenticate()
        
        import httpx
        url = "https://my.tado.com/api/v2/me"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            me_data = resp.json()
            
            # Get homes from user data
            homes = me_data.get("homes", [])
            home_list = []
            for home in homes:
                home_list.append({
                    "id": home.get("id"),
                    "name": home.get("name"),
                    "dateTimeZone": home.get("dateTimeZone"),
                    "temperatureUnit": home.get("temperatureUnit")
                })
            
            self._log.info(f"Found {len(home_list)} homes")
            return home_list
        except httpx.HTTPStatusError as e:
            self._log.error(f"Failed to get homes: {e}")
            raise

    def get_demand_events(
        self,
        period_from: dt.datetime,
        period_to: dt.datetime
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical demand events for all TRVs using dayReport endpoint.
        Returns a list of events with actual historical timestamps and heating demands.
        """
        import httpx
        
        if not self._access_token:
            self.authenticate()
        
        events = []
        devices = self.enumerate_devices()
        
        # Iterate day by day through the period
        current_date = period_from.date()
        end_date = period_to.date()
        
        while current_date <= end_date:
            date_str = current_date.isoformat()
            
            for device in devices:
                if device.device_type != "trv":
                    continue
                    
                try:
                    day_events = self._get_day_demand_events(device, date_str)
                    events.extend(day_events)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        self._log.info(
                            f"No data available for zone {device.zone_id} on {date_str} (404)"
                        )
                    else:
                        self._log.warning(
                            f"HTTP error for zone {device.zone_id} on {date_str}: "
                            f"{e.response.status_code}"
                        )
                    continue
                except Exception as e:
                    self._log.warning(
                        f"Failed to get demand data for zone {device.zone_id} on "
                        f"{date_str}: {e}"
                    )
                    continue
            
            current_date += dt.timedelta(days=1)
        
        return events

    def _get_day_demand_events(self, device: TadoDevice, date_str: str) -> List[Dict[str, Any]]:
        """
        Get heating demand events for a specific device and date using dayReport.
        """
        import httpx
        
        url = (
            f"https://my.tado.com/api/v2/homes/{self.settings.home_id}/zones/"
            f"{device.zone_id}/dayReport?date={date_str}"
        )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        
        resp = httpx.get(url, headers=headers)
        resp.raise_for_status()
        day_data = resp.json()
        
        events = []
        
        # Extract callForHeat intervals
        call_for_heat = day_data.get("callForHeat", {})
        if call_for_heat.get("dataIntervals"):
            for interval in call_for_heat["dataIntervals"]:
                # Only include intervals where heating is actually requested
                if interval["value"] != "NONE":
                    events.append({
                        "trv_id": device.device_id,
                        "zone_id": device.zone_id,
                        "requested": True,
                        "heat_demand": interval["value"],  # e.g., "LOW", "MEDIUM", "HIGH"
                        "timestamp": interval["from"],
                        "duration_minutes": self._calculate_interval_minutes(
                            interval["from"], interval["to"])
                    })
        
        return events

    def _calculate_interval_minutes(self, from_time: str, to_time: str) -> int:
        """Calculate duration between two ISO timestamps in minutes."""
        from_dt = dt.datetime.fromisoformat(from_time.replace('Z', '+00:00'))
        to_dt = dt.datetime.fromisoformat(to_time.replace('Z', '+00:00'))
        return int((to_dt - from_dt).total_seconds() / 60)

    def get_temperature_data(self, device: TadoDevice, 
                           period_from: dt.datetime = None, 
                           period_to: dt.datetime = None) -> List[Dict[str, Any]]:
        """
        Get historical temperature readings for a device using dayReport endpoint.
        
        Args:
            device: The Tado device to query
            period_from: Start of period (default: 24 hours ago)
            period_to: End of period (default: now)
            
        Returns:
            List of temperature records with actual historical timestamps
        """
        import httpx
        
        if not self._access_token:
            self.authenticate()
            
        if period_from is None:
            period_from = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
        if period_to is None:
            period_to = dt.datetime.now(dt.timezone.utc)
        
        temperature_records = []
        
        # Iterate day by day through the period
        current_date = period_from.date()
        end_date = period_to.date()
        
        while current_date <= end_date:
            date_str = current_date.isoformat()
            
            try:
                day_records = self._get_day_temperature_data(device, date_str)
                
                # Filter records to the requested time range
                for record in day_records:
                    record_time = dt.datetime.fromisoformat(
                        record["timestamp"].replace('Z', '+00:00'))
                    if period_from <= record_time <= period_to:
                        temperature_records.append(record)
                        
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    self._log.info(
                        f"No temperature data available for zone {device.zone_id} "
                        f"on {date_str} (404)"
                    )
                else:
                    self._log.warning(
                        f"HTTP error for zone {device.zone_id} on {date_str}: "
                        f"{e.response.status_code}"
                    )
                continue
            except Exception as e:
                self._log.warning(
                    f"Failed to get temperature data for zone {device.zone_id} on "
                    f"{date_str}: {e}"
                )
                continue
            
            current_date += dt.timedelta(days=1)
        
        return temperature_records

    def _get_day_temperature_data(self, device: TadoDevice, date_str: str) -> List[Dict[str, Any]]:
        """
        Get temperature and humidity readings for a specific device and date using dayReport.
        Fixed version based on actual API response structure.
        """
        import httpx
        
        url = (
            f"https://my.tado.com/api/v2/homes/{self.settings.home_id}/zones/"
            f"{device.zone_id}/dayReport?date={date_str}"
        )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        
        resp = httpx.get(url, headers=headers)
        resp.raise_for_status()
        day_data = resp.json()
        
        temperature_records = []
        
        # Extract measured data - this is the correct structure based on API response
        measured_data = day_data.get("measuredData")
        if not measured_data or not isinstance(measured_data, dict):
            self._log.info(f"No measured data found for device {device.device_id} on {date_str}")
            return []
        
        # Get inside temperature readings
        inside_temp = measured_data.get("insideTemperature")
        if inside_temp and isinstance(inside_temp, dict):
            data_points = inside_temp.get("dataPoints")
            if data_points and isinstance(data_points, list):
                for point in data_points:
                    try:
                        # Comprehensive null checking
                        if not point or not isinstance(point, dict):
                            continue
                        
                        timestamp = point.get("timestamp")
                        value = point.get("value")
                        
                        if not timestamp or not value or not isinstance(value, dict):
                            continue
                            
                        celsius_temp = value.get("celsius")
                        if celsius_temp is not None and isinstance(celsius_temp, (int, float)):
                            temp_record = {
                                "device_id": device.device_id,
                                "zone_id": device.zone_id,
                                "temperature": celsius_temp,
                                "timestamp": timestamp,
                                "sensor_type": "inside"
                            }
                            temperature_records.append(temp_record)
                    except (AttributeError, TypeError, KeyError) as e:
                        self._log.warning(
                            f"Error processing temperature point for {device.device_id}: {e}"
                        )
                        continue
        
        # Get humidity readings and create lookup by timestamp
        humidity_by_timestamp = {}
        humidity_data = measured_data.get("humidity")
        if humidity_data and isinstance(humidity_data, dict):
            data_points = humidity_data.get("dataPoints")
            if data_points and isinstance(data_points, list):
                for point in data_points:
                    try:
                        if not point or not isinstance(point, dict):
                            continue
                        
                        timestamp = point.get("timestamp")
                        value = point.get("value")
                        
                        if timestamp and value is not None and isinstance(value, (int, float)):
                            humidity_by_timestamp[timestamp] = value
                    except (AttributeError, TypeError, KeyError) as e:
                        self._log.warning(
                            f"Error processing humidity point for {device.device_id}: {e}"
                        )
                        continue
        
        # Add humidity to temperature records where timestamps match
        for record in temperature_records:
            timestamp = record.get("timestamp")
            if timestamp and timestamp in humidity_by_timestamp:
                record["humidity"] = humidity_by_timestamp[timestamp]
        
        # Get target temperature from settings intervals
        settings_data = day_data.get("settings")
        if settings_data and isinstance(settings_data, dict):
            data_intervals = settings_data.get("dataIntervals")
            if data_intervals and isinstance(data_intervals, list):
                for interval in data_intervals:
                    try:
                        if not interval or not isinstance(interval, dict):
                            continue
                        
                        setting = interval.get("value")
                        interval_from = interval.get("from")
                        
                        if (not setting or not isinstance(setting, dict) or 
                            not interval_from):
                            continue
                        
                        # Check if power is ON and temperature is set
                        power = setting.get("power")
                        temp_setting = setting.get("temperature")
                        
                        if (power == "ON" and temp_setting and 
                            isinstance(temp_setting, dict)):
                            celsius_target = temp_setting.get("celsius")
                            if celsius_target is not None and isinstance(celsius_target, (int, float)):
                                target_record = {
                                    "device_id": device.device_id,
                                    "zone_id": device.zone_id,
                                    "temperature": celsius_target,
                                    "timestamp": interval_from,
                                    "sensor_type": "target"
                                }
                                temperature_records.append(target_record)
                    except (AttributeError, TypeError, KeyError) as e:
                        self._log.warning(
                            f"Error processing settings interval for {device.device_id}: {e}"
                        )
                        continue
        
        return temperature_records

    def get_temperature_events(self, device: TadoDevice, period_from: dt.datetime, period_to: dt.datetime) -> List[Dict[str, Any]]:
        """
        Compatibility method that calls get_temperature_data.
        """
        return self.get_temperature_data(device, period_from, period_to)

    def get_heating_data(self, device: TadoDevice,
                        period_from: dt.datetime = None,
                        period_to: dt.datetime = None) -> List[Dict[str, Any]]:
        """
        Get heating/cooling activity data for a device.
        
        Args:
            device: The Tado device to query
            period_from: Start of period (default: 24 hours ago) 
            period_to: End of period (default: now)
            
        Returns:
            List of heating activity records with timestamps
        """
        # TODO: Implement Tado API calls
        raise NotImplementedError("Tado heating data retrieval not yet implemented")
    
    def get_temperature_events(self, device: TadoDevice, period_from: dt.datetime, period_to: dt.datetime) -> List[Dict[str, Any]]:
        """
        Fetch temperature readings for a TRV over a time period.
        Returns a list of events: {trv_id, zone_id, temperature, timestamp}
        Timestamps are normalized to UTC ISO 8601.
        """
        events = []
        # TODO: Replace with real Tado API call to fetch temperature data for this TRV
        # Example endpoint: /api/v2/homes/{home_id}/zones/{zone_id}/temperature
        # Simulate with placeholder data for now
        event = {
            "trv_id": device.device_id,
            "zone_id": device.zone_id,
            "temperature": 21.5,  # Example temperature
            "timestamp": period_from.replace(tzinfo=dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        }
        events.append(event)
        return events
    
    def enumerate_devices(self) -> list:
        """
        Fetch all zones/devices for the configured home from Tado API.
        Returns a list of TadoDevice objects.
        """
        if not self._access_token:
            self.authenticate()
        
        import httpx
        url = (
            f"https://my.tado.com/api/v2/homes/{self.settings.home_id}/zones"
        )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        
        try:
            resp = httpx.get(url, headers=headers)
            resp.raise_for_status()
            zones = resp.json()
            devices = []
            for zone in zones:
                if zone.get("type") == "HEATING":
                    devices.append(TadoDevice(
                        device_id=str(zone["id"]),
                        name=zone.get("name", "TRV"),
                        device_type="trv",
                        zone_id=str(zone["id"]),
                    ))
            self._log.info(f"Found {len(devices)} heating zones")
            return devices
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                self._log.error(f"Access denied to Tado API. Check token permissions and home_id: {self.settings.home_id}")
                # Return placeholder devices for testing
                self._log.warning("Using placeholder device for testing")
                return [TadoDevice(
                    device_id="test_trv_1",
                    name="Test TRV",
                    device_type="trv",
                    zone_id="1"
                )]
            else:
                raise

    def get_day_report(self, device: TadoDevice, date_str: str) -> Dict[str, Any]:
        """Fetch raw dayReport JSON once for a device+date (no parsing)."""
        import httpx
        if not self._access_token:
            self.authenticate()
        
        # Proactively refresh token if it's close to expiring
        self._ensure_valid_token()
        
        url = (
            f"https://my.tado.com/api/v2/homes/{self.settings.home_id}/zones/"
            f"{device.zone_id}/dayReport?date={date_str}"
        )
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = httpx.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def parse_day_report(self, device: TadoDevice, day_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Parse a dayReport JSON for both demand events and temperature records.
        Returns (demand_events, temperature_records)."""
        demand_events: List[Dict[str, Any]] = []
        temperature_records: List[Dict[str, Any]] = []
        date_prefix = None
        # Demand (callForHeat)
        call_for_heat = day_data.get("callForHeat", {})
        intervals = call_for_heat.get("dataIntervals") or []
        for interval in intervals:
            try:
                if not interval or interval.get("value") == "NONE":
                    continue
                demand_events.append({
                    "trv_id": device.device_id,
                    "zone_id": device.zone_id,
                    "requested": True,
                    "heat_demand": interval.get("value"),
                    "timestamp": interval.get("from"),
                    "duration_minutes": (
                        self._calculate_interval_minutes(
                            interval.get("from"), interval.get("to")
                        ) if interval.get("from") and interval.get("to") else None
                    )
                })
            except Exception:
                continue
        # Temperatures (inside + target) and humidity
        measured = day_data.get("measuredData") or {}
        inside_temp = measured.get("insideTemperature") or {}
        temp_points = inside_temp.get("dataPoints") or []
        humidity_points = (measured.get("humidity") or {}).get("dataPoints") or []
        humidity_lookup = {}
        for hp in humidity_points:
            try:
                ts = hp.get("timestamp"); val = hp.get("value")
                if ts and isinstance(val, (int, float)):
                    humidity_lookup[ts] = val
            except Exception:
                continue
        for tp in temp_points:
            try:
                val = tp.get("value") or {}
                c = val.get("celsius")
                ts = tp.get("timestamp")
                if ts and isinstance(c, (int, float)):
                    rec = {
                        "device_id": device.device_id,
                        "zone_id": device.zone_id,
                        "temperature": c,
                        "timestamp": ts,
                        "sensor_type": "inside"
                    }
                    if ts in humidity_lookup:
                        rec["humidity"] = humidity_lookup[ts]
                    temperature_records.append(rec)
            except Exception:
                continue
        # Target temps from settings
        settings_section = day_data.get("settings") or {}
        settings_intervals = settings_section.get("dataIntervals") or []
        for si in settings_intervals:
            try:
                val = si.get("value") or {}
                if val.get("power") == "ON":
                    temp_obj = val.get("temperature") or {}
                    c = temp_obj.get("celsius")
                    ts = si.get("from")
                    if ts and isinstance(c, (int, float)):
                        temperature_records.append({
                            "device_id": device.device_id,
                            "zone_id": device.zone_id,
                            "temperature": c,
                            "timestamp": ts,
                            "sensor_type": "target"
                        })
            except Exception:
                continue
        return demand_events, temperature_records

    def iterate_day_reports(self, period_from: dt.datetime, period_to: dt.datetime) -> Iterator[Tuple[str, TadoDevice, Dict[str, Any]]]:
    """
    Yield (date_str, device, day_report_json) for each device/day in range
    (single fetch per pair).
    """
        devices = [d for d in self.enumerate_devices() if d.device_type == "trv"]
        current_date = period_from.date()
        end_date = period_to.date()
        while current_date <= end_date:
            date_str = current_date.isoformat()
            for device in devices:
                try:
                    data = self.get_day_report(device, date_str)
                    yield date_str, device, data
                except Exception as e:
                    self._log.warning(
                        f"Failed dayReport fetch for zone {device.zone_id} on {date_str}: {e}"
                    )
                    continue
            current_date += dt.timedelta(days=1)