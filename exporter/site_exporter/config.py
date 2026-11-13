"""Чтение и проверка списка сайтов (targets.yml)."""

from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator


class Target(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    url: HttpUrl
    expected_status: list[int] = [200]
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @property
    def is_https(self) -> bool:
        return urlparse(str(self.url)).scheme == "https"


class Config(BaseModel):
    interval_seconds: int = Field(default=30, ge=5, le=3600)
    targets: list[Target] = Field(min_length=1)

    @field_validator("targets")
    @classmethod
    def names_are_unique(cls, targets: list[Target]) -> list[Target]:
        names = [t.name for t in targets]
        if len(names) != len(set(names)):
            raise ValueError("имена целей (name) должны быть уникальными")
        return targets


def load_config(path: str | Path) -> Config:
    with open(path, encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
