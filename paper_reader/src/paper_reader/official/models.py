from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, Self
from urllib.parse import urlsplit
import ipaddress

from pydantic import JsonValue, SecretStr, StringConstraints, field_validator, model_validator

from paper_reader.contracts import ArtifactRef, NonNegativeInt, PortableIdentifier, Rfc3339Utc, Sha256, StrictContractModel

Text = Annotated[str, StringConstraints(min_length=1)]
ItemKey = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{8}$")]
JsonObject = dict[str, JsonValue]


class LibraryContext(StrictContractModel):
    base_url: str
    server_id: Text
    api_version: Literal[3]
    library_type: Literal["users", "groups"]
    library_id: NonNegativeInt

    @field_validator("api_version", mode="before")
    @classmethod
    def require_integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("api_version must be an integer")
        return value

    @model_validator(mode="after")
    def require_local_api(self) -> Self:
        parsed = urlsplit(self.base_url)
        try:
            local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
            port = parsed.port
        except ValueError:
            local = False
            port = None
        if (not local or parsed.scheme != "http" or port is None or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment or parsed.path != "/api/"):
            raise ValueError("base_url must be a loopback HTTP API URL with an explicit port")
        return self


class ItemData(StrictContractModel):
    """Fields consumed by the core; the unprojected API object lives in raw_json."""
    item_type: Text
    title: str = ""
    extra: str = ""
    parent_key: ItemKey | None = None
    collections: tuple[ItemKey, ...] = ()
    tags: tuple[str, ...] = ()
    note: str = ""
    filename: str = ""
    content_type: str = ""


class ItemSnapshot(StrictContractModel):
    key: ItemKey
    version: NonNegativeInt
    data: ItemData
    raw_json: JsonObject


class CollectionSnapshot(StrictContractModel):
    key: ItemKey
    parent_key: ItemKey | None
    name: Text
    version: NonNegativeInt


class RemoteOperationObservation(StrictContractModel):
    operation_id: PortableIdentifier
    item_keys: tuple[ItemKey, ...]
    status: Literal['verified', 'missing', 'unavailable', 'conflict']
    readback: ArtifactRef
    pdf_sha256: Sha256 | None = None
    note_sha256: Sha256 | None = None


class RemoteObservation(StrictContractModel):
    """Independent peer readbacks bound to one exact local execution result."""
    context: LibraryContext
    observed_at: Rfc3339Utc
    local_result: ArtifactRef
    operations: tuple[RemoteOperationObservation, ...]


class SyncReport(StrictContractModel):
    local_result: ArtifactRef
    local_status: Literal['local_verified', 'incomplete', 'conflict_needs_review']
    sync_status: Literal['sync_unobserved', 'remote_observed', 'conflict_needs_review']
    observation_status: Literal['unknown', 'verified', 'missing', 'unavailable', 'conflict']
    remote_observation: RemoteObservation | None


class ZoteroSelection(StrictContractModel):
    context: LibraryContext
    item_key: ItemKey
    parent: ItemSnapshot
    parent_snapshot: ArtifactRef

    @model_validator(mode="after")
    def require_selected_parent(self) -> Self:
        if self.item_key != self.parent.key:
            raise ValueError("selected key must match the authoritative parent")
        return self


class ZoteroGateway(Protocol):
    """Official API boundary. Only the approved executor calls mutation methods."""
    context: LibraryContext

    def get_item(self, key: str) -> ItemSnapshot: ...
    def item_exists(self, key: str) -> bool: ...
    def get_children(self, key: str) -> tuple[ItemSnapshot, ...]: ...
    def search_items(self, query: str) -> tuple[ItemSnapshot, ...]: ...
    def get_collections(self) -> tuple[CollectionSnapshot, ...]: ...
    def get_library_version(self) -> int: ...
    def get_file_path(self, key: str) -> Path: ...
    def create_items(self, payloads: tuple[ItemCreate, ...], *, library_version: int,
                     credentials: SecretStr, write_token: str) -> tuple[ItemWriteResult, ...]: ...
    def patch_item(self, key: str, patch: ItemPatch, *, expected_version: int,
                   credentials: SecretStr) -> ItemWriteResult: ...
    def request_upload(self, attachment_key: str, source, *, filename: str,
                       expected_file_md5: str | None, credentials: SecretStr) -> UploadPermit: ...
    def send_upload(self, permit: UploadPermit, source) -> UploadReceipt: ...
    def register_upload(self, permit: UploadPermit, *, expected_file_md5: str | None,
                        credentials: SecretStr) -> ItemWriteResult: ...


class CredentialProvider(Protocol):
    """Process-local application authorization, separate from content approval."""
    def get_key(self, context: LibraryContext) -> SecretStr: ...
    def invalidate(self, context: LibraryContext) -> None: ...


class ItemCreate(StrictContractModel):
    """Exact child note request, retained for existing T5 callers."""
    key: ItemKey
    parent_key: ItemKey
    html: Text
    tags: tuple[str, ...]


ImportItemType = Literal['journalArticle', 'conferencePaper', 'preprint', 'report', 'book', 'bookSection']


class ParentCreate(StrictContractModel):
    key: ItemKey
    item_type: ImportItemType
    title: Text
    authors: tuple[str, ...]
    date: str
    extra: str
    collections: tuple[ItemKey, ...]


class AttachmentCreate(StrictContractModel):
    key: ItemKey
    parent_key: ItemKey
    title: Text
    filename: Text
    content_type: Literal['application/pdf'] = 'application/pdf'
    link_mode: Literal['imported_file'] = 'imported_file'


class ItemPatch(StrictContractModel):
    collections: tuple[ItemKey, ...]


@dataclass(frozen=True, repr=False)
class UploadPermit:
    """Transient; a missing key means the server already has these bytes."""
    context: LibraryContext
    attachment_key: str
    upload_key: SecretStr | None
    md5: str
    content_type: str


@dataclass(frozen=True, repr=False)
class UploadReceipt:
    attachment_key: str
    md5: str
    size_bytes: int


WriteErrorCode = Literal['auth_required', 'auth_denied', 'rate_limited', 'plan_stale',
                         'instance_changed', 'verification_failed', 'write_uncertain']


class ItemWriteResult(StrictContractModel):
    key: ItemKey
    version: NonNegativeInt | None
    state: Literal['succeeded', 'failed', 'unknown']
    error_code: WriteErrorCode | None


class HttpResponse(StrictContractModel):
    status: int
    headers: dict[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str],
                body: bytes | None) -> HttpResponse: ...
