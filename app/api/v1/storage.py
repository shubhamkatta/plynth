"""HTTP surface for the Storage API (`docs/architecture.md` § 6.3).

Routes:
    POST   /storage/collections                 register a collection
    PUT    /storage/{collection}/{key}          upsert a document
    GET    /storage/{collection}/{key}          read a document
    GET    /storage/{collection}?since=         list / delta-sync
    DELETE /storage/{collection}/{key}          remove a document

Permissions: `storage:read` for GET, `storage:write` for POST/PUT,
`storage:delete` for DELETE.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, actor_id, require_permission
from app.core.tenant import current_tenant_id
from app.models.storage import StorageDocument
from app.schemas.storage import (
    StorageCollectionCreateRequest,
    StorageCollectionResponse,
    StorageDocumentListItem,
    StorageListResponse,
    StoragePutRequest,
    StorageValueResponse,
)
from app.services import storage as storage_svc

router = APIRouter()

CollectionPath = Annotated[
    str,
    Path(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-\.]+$"),
]
# Slashes in keys break the path matcher; restrict to a sane charset that
# still covers UUIDs, slugs, and dotted identifiers.
KeyPath = Annotated[
    str,
    Path(min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_\-\.:]+$"),
]


def _serialise(doc: StorageDocument) -> StorageValueResponse:
    return StorageValueResponse(
        key=doc.key,
        value=doc.value,
        version=doc.version,
        expires_at=doc.expires_at,
        updated_at=doc.updated_at,
    )


@router.post(
    "/collections",
    response_model=StorageCollectionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("storage:write"))],
)
async def create_collection(
    payload: StorageCollectionCreateRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageCollectionResponse:
    tid = current_tenant_id() or user.tenant_id
    coll = await storage_svc.create_collection(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        name=payload.name,
        description=payload.description,
        default_ttl_seconds=payload.default_ttl_seconds,
        actor_user_id=actor_id(user),
    )
    return StorageCollectionResponse.model_validate(coll)


@router.put(
    "/{collection}/{key}",
    response_model=StorageValueResponse,
    dependencies=[Depends(require_permission("storage:write"))],
)
async def put_document(
    collection: CollectionPath,
    key: KeyPath,
    payload: StoragePutRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageValueResponse:
    tid = current_tenant_id() or user.tenant_id
    doc = await storage_svc.put_document(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        collection_name=collection,
        key=key,
        value=payload.value,
        ttl_seconds=payload.ttl_seconds,
        if_version=payload.if_version,
        actor_user_id=actor_id(user),
    )
    return _serialise(doc)


@router.get(
    "/{collection}/{key}",
    response_model=StorageValueResponse,
    dependencies=[Depends(require_permission("storage:read"))],
)
async def get_document(
    collection: CollectionPath,
    key: KeyPath,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StorageValueResponse:
    tid = current_tenant_id() or user.tenant_id
    doc = await storage_svc.get_document(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        collection_name=collection,
        key=key,
    )
    return _serialise(doc)


@router.get(
    "/{collection}",
    response_model=StorageListResponse,
    dependencies=[Depends(require_permission("storage:read"))],
)
async def list_documents(
    collection: CollectionPath,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    since: Annotated[datetime | None, Query()] = None,
    prefix: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> StorageListResponse:
    tid = current_tenant_id() or user.tenant_id
    docs = await storage_svc.list_documents(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        collection_name=collection,
        since=since,
        prefix=prefix,
        limit=limit,
    )
    return StorageListResponse(
        items=[
            StorageDocumentListItem(
                key=d.key,
                version=d.version,
                updated_at=d.updated_at,
                expires_at=d.expires_at,
            )
            for d in docs
        ]
    )


@router.delete(
    "/{collection}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("storage:delete"))],
)
async def delete_document(
    collection: CollectionPath,
    key: KeyPath,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    tid = current_tenant_id() or user.tenant_id
    await storage_svc.delete_document(
        db,
        product_id=user.product_id,
        tenant_id=tid,
        collection_name=collection,
        key=key,
        actor_user_id=actor_id(user),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
