from __future__ import annotations

from .provider import BaseDataProvider, ProviderHealth


class ProviderRegistry:
    """Central lookup of every registered data provider.

    Enforces that every provider declares a classification (PUBLIC/LICENSED/
    USER_PROVIDED/SIMULATED) at registration time — there is no "unclassified" path
    for data to enter the platform.
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseDataProvider] = {}

    def register(self, provider: BaseDataProvider) -> None:
        if provider.classification is None:  # pragma: no cover - defensive
            raise ValueError(f"Provider {provider.provider_id} must declare a classification")
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> BaseDataProvider:
        return self._providers[provider_id]

    def all(self) -> list[BaseDataProvider]:
        return list(self._providers.values())

    async def health_snapshot(self) -> list[ProviderHealth]:
        return [await p.health_check() for p in self._providers.values()]
