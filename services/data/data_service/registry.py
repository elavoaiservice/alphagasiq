from __future__ import annotations

from config import get_settings
from data_sdk import ProviderRegistry

from .providers.eia import EIAProvider
from .providers.iso_rto import ISORTOProvider
from .providers.mock_market_data import MockCMEProvider, MockICEProvider
from .providers.mock_news import MockNewsProvider
from .providers.nhc import TropicalWeatherConnector
from .providers.noaa import NOAAProvider
from .providers.rss_news import RSSNewsProvider
from .providers.sec_edgar import SECEdgarProvider
from .providers.stubs import ALL_STUBS


def build_default_registry() -> ProviderRegistry:
    """Wires up every provider the platform knows about.

    LICENSED/paid connectors (CME, ICE) default to their `Mock*Provider` unless the
    operator has explicitly opted out via settings — this is what lets
    `docker compose up` run the full dashboard with zero commercial subscriptions.
    """
    settings = get_settings()
    registry = ProviderRegistry()

    registry.register(EIAProvider(api_key=settings.eia_api_key))
    registry.register(NOAAProvider(contact_token=settings.noaa_api_token))
    registry.register(ISORTOProvider(api_key=settings.eia_api_key))
    registry.register(TropicalWeatherConnector())
    registry.register(SECEdgarProvider(contact_email=settings.sec_edgar_contact_email))
    # Real free news: comma-separated RSS URLs from RSS_NEWS_FEEDS (set in Configuration).
    rss_feeds = [u.strip() for u in (settings.rss_news_feeds or "").split(",") if u.strip()]
    registry.register(RSSNewsProvider(feed_urls=rss_feeds))

    if settings.use_mock_market_data:
        registry.register(MockCMEProvider())
        registry.register(MockICEProvider())

    if settings.use_mock_news:
        registry.register(MockNewsProvider())

    for stub in ALL_STUBS:
        registry.register(stub)

    # Real market data: when the operator turns off mock market data, wire the real
    # NYMEX Henry Hub futures curve (Yahoo Finance, free/delayed) in place of the
    # `cme_live` stub, so the dashboard shows real HH M1/M2/strip prices. (ICE/TTF
    # stays simulated — real TTF is EUR/MWh and needs FX + unit conversion.)
    if not settings.use_mock_market_data:
        from .providers.cme_yahoo import YahooHenryHubProvider

        registry.register(YahooHenryHubProvider())

    return registry
