from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class WeatherLocation:
    """Configuration for a weather monitoring location."""
    location_id: str
    name: str
    latitude: float
    longitude: float
    timezone: Optional[str] = None

@dataclass  
class WeatherSettings:
    """Configuration for Weather API client."""
    api_key: str
    provider: str  # 'openweathermap', 'weatherapi', etc.
    locations: List[WeatherLocation] = None
    
    @staticmethod
    def from_env() -> 'WeatherSettings':
        """Create Weather settings from environment variables (future implementation)."""
        # TODO: Implement when Weather integration is ready
        # api_key = os.environ['WEATHER_API_KEY']
        # provider = os.environ.get('WEATHER_PROVIDER', 'openweathermap')
        # return WeatherSettings(api_key=api_key, provider=provider)
        raise NotImplementedError("Weather integration not yet implemented")