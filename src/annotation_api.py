import asyncio
from typing import Annotated
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field
from src.services.annotations import AnnotationStore
from src.services.collection import CollectionService


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Version(Input):
    version: int = Field(ge=1, le=2**63-1)


class TagName(Input):
    name: str = Field(min_length=1, max_length=80)


class TagUpdate(Version, TagName):
    pass


class AnnotationUpdate(Version):
    display_name: str = Field(default='', max_length=240)
    tag_ids: list[int] = Field(default_factory=list, max_length=64)


class AnnotationCopy(Input):
    source_id: str = Field(pattern=r'^cron-v[12]-[0-9a-f]{64}$')
    target_id: str = Field(pattern=r'^cron-v[12]-[0-9a-f]{64}$')
    source_version: int = Field(ge=1, le=2**63-1)
    target_version: int = Field(ge=1, le=2**63-1)
    overwrite: bool = False


def annotation_router(store: AnnotationStore, service: CollectionService):
    router = APIRouter(prefix='/api')

    def current(key):
        if service.annotation_error:
            raise HTTPException(503, '表示名とタグの状態を確認できません')
        if not any(not c.stale and t.definition_id == key for c in service.results.values() for t in c.tasks):
            raise HTTPException(409, '現在の定義を確認できません。再取得してください')

    @router.get('/tags')
    def tags():
        return store.snapshot()['tags']

    @router.post('/tags', status_code=201)
    def create_tag(body: TagName):
        return store.create_tag(body.name)

    @router.put('/tags/{tag_id}')
    def rename_tag(tag_id: Annotated[int, Path(ge=1, le=2**63-1)], body: TagUpdate):
        return store.change_tag(tag_id, body.version, body.name)

    @router.delete('/tags/{tag_id}')
    def delete_tag(tag_id: Annotated[int, Path(ge=1, le=2**63-1)], body: Version):
        return store.change_tag(tag_id, body.version)

    @router.get('/annotations')
    def annotations():
        return list(store.snapshot()['annotations'].values())

    @router.put('/annotations/{definition_id}')
    async def update(definition_id: str, body: AnnotationUpdate):
        async with service.lock:
            current(definition_id)
            return await asyncio.to_thread(store.update, definition_id, body.version, body.display_name, body.tag_ids)

    @router.delete('/annotations/{definition_id}')
    async def reset(definition_id: str, body: Version):
        async with service.lock:
            return await asyncio.to_thread(store.update, definition_id, body.version, '', [], require_present=False)

    @router.post('/annotations/copy')
    async def copy(body: AnnotationCopy):
        async with service.lock:
            current(body.target_id)
            return await asyncio.to_thread(store.copy, body.source_id, body.target_id,
                body.source_version, body.target_version, overwrite=body.overwrite)

    return router
