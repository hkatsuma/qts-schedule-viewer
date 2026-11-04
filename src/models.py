from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, PrivateAttr


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
    definition_id: str | None = None
    duplicate_count: int = 1
    name: str
    description: str = ''
    category: str = 'system'
    provider: str = 'QTS'
    enabled: bool | None = True
    schedule: Schedule
    next_runs: list[datetime] = Field(default_factory=list)
    duration_seconds: int | None = None
    runs_per_active_day: int | None = None
    source: Source
    command: str
    command_available: bool = False
    # Never serialize the original command, including nested collections.
    _raw_command: str | None = PrivateAttr(default=None)
    configuration_location: str = 'QTS / cron'
    collection_status: str = 'ok'
    collected_at: datetime | None = None
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
