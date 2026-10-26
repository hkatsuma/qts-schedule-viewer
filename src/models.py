from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class Schedule(BaseModel):
    type: str = 'cron'
    expression: str
    timezone: str
    description: str


class Source(BaseModel):
    collector: str
    type: str = 'config'
    location: str


class Task(BaseModel):
    id: str
    name: str
    description: str = ''
    category: str = 'system'
    provider: str = 'QTS'
    enabled: bool | None = True
    schedule: Schedule
    next_runs: list[datetime] = Field(default_factory=list)
    duration_seconds: int | None = None
    source: Source
    command: str
    configuration_location: str = 'QTS / cron（管理画面の有無は実機で確認）'
    collection_status: str = 'ok'
    warnings: list[str] = Field(default_factory=list)


class Collection(BaseModel):
    collector: str
    status: Literal['ok', 'empty', 'partial', 'unsupported', 'permission_denied', 'unavailable', 'parse_error']
    message: str
    attempted_at: datetime
    last_success_at: datetime | None = None
    previous_status: str | None = None
    stale: bool = False
    tasks: list[Task] = Field(default_factory=list)
