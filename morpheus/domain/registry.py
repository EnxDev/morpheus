from __future__ import annotations

from domain.config import DomainConfig


class DomainRegistry:
    _configs: dict[str, DomainConfig] = {}
    _default: str | None = None

    @classmethod
    def register(cls, config: DomainConfig, *, default: bool = False) -> None:
        cls._configs[config.name] = config
        if default or cls._default is None:
            cls._default = config.name

    @classmethod
    def get(cls, name: str) -> DomainConfig:
        if name not in cls._configs:
            raise KeyError(f"Domain config '{name}' not registered")
        return cls._configs[name]

    @classmethod
    def default(cls) -> DomainConfig:
        if cls._default is None:
            # Auto-load default BI config on first access
            from domain.default_bi import DEFAULT_BI_CONFIG
            cls.register(DEFAULT_BI_CONFIG, default=True)
        return cls._configs[cls._default]

    @classmethod
    def list_domains(cls) -> list[str]:
        return list(cls._configs.keys())

    @classmethod
    def delete(cls, name: str) -> None:
        if name not in cls._configs:
            raise KeyError(f"Domain config '{name}' not registered")
        del cls._configs[name]
        if cls._default == name:
            cls._default = next(iter(cls._configs), None)

    @classmethod
    def clear(cls) -> None:
        cls._configs.clear()
        cls._default = None
