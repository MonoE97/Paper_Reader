from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Protocol, Self
from urllib.parse import urlsplit
import ipaddress

from pydantic import JsonValue, SecretStr, StringConstraints, field_validator, model_validator

from paper_reader.contracts import ArtifactRef, NonNegativeInt, StrictContractModel

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
    """Read boundary. Executor-only mutation methods are added with T5/T7."""
    context: LibraryContext

    def get_item(self, key: str) -> ItemSnapshot: ...
    def get_children(self, key: str) -> tuple[ItemSnapshot, ...]: ...
    def search_items(self, query: str) -> tuple[ItemSnapshot, ...]: ...
    def get_collections(self) -> tuple[CollectionSnapshot, ...]: ...
    def get_library_version(self) -> int: ...
    def get_file_path(self, key: str) -> Path: ...


class CredentialProvider(Protocol):
    """Process-local application authorization, separate from content approval."""
    def get_key(self, context: LibraryContext) -> SecretStr: ...
