import enum
from typing import Optional

from pydantic import Field

from ...api_handlers import BaseRequestModel
from ...data.storage.registries.types import ModelTarget
from ...types import QuotaConfig, VFolderID


class QuotaScopeReq(BaseRequestModel):
    options: Optional[QuotaConfig] = Field(
        default=None,
        description="The options for the quota scope.",
    )


class GetVFolderMetaReq(BaseRequestModel):
    subpath: str = Field(
        description="The subpath of the virtual folder.",
    )


class CloneVFolderReq(BaseRequestModel):
    dst_vfolder_id: VFolderID = Field(
        description="The destination virtual folder ID.",
        alias="dst_vfid",
    )


class ObjectStorageOperationType(enum.StrEnum):
    """Enumeration of supported object storage operations."""

    UPLOAD = "upload"
    DOWNLOAD = "download"
    INFO = "info"
    DELETE = "delete"
    PRESIGNED_UPLOAD = "presigned_upload"
    PRESIGNED_DOWNLOAD = "presigned_download"


class ObjectStorageTokenData(BaseRequestModel):
    """
    JWT token data for authenticated object storage operations.

    This token contains all the necessary information to perform
    secure operations on object storage systems like S3.
    """

    op: ObjectStorageOperationType = Field(description="The type of storage operation to perform")
    bucket: str = Field(description="The name of the storage bucket to operate on")
    key: str = Field(description="The object key (path) within the bucket")
    expiration: Optional[int] = Field(
        default=None, gt=0, le=604800, description="Token expiration time in seconds (max 7 days)"
    )
    content_type: Optional[str] = Field(
        default=None, description="MIME type of the object for upload operations"
    )
    min_size: Optional[int] = Field(
        default=None, ge=0, description="Minimum allowed size in bytes for upload operations"
    )
    max_size: Optional[int] = Field(
        default=None, gt=0, description="Maximum allowed size in bytes for upload operations"
    )
    filename: Optional[str] = Field(
        default=None, description="Original filename for download operations"
    )


# HuggingFace API Request Models
class HuggingFaceScanModelsReq(BaseRequestModel):
    """Request for scanning HuggingFace models."""

    registry_name: str = Field(
        description="""
        Name of the HuggingFace registry to scan.
        This should match the configured registry name in the system.
        """,
        examples=["huggingface", "my-huggingface-registry"],
    )
    limit: int = Field(
        default=10,
        ge=1,
        description="""
        Maximum number of models to retrieve.
        Controls the number of models returned in a single request.
        """,
        examples=[10, 50, 100],
    )
    search: Optional[str] = Field(
        default=None,
        description="""
        Search query to filter models by name, description, or tags.
        Leave empty to retrieve all models without filtering.
        """,
        examples=[None, "GPT", "microsoft", "text-generation"],
    )
    order: str = Field(
        default="downloads",
        description="""
        Sort criteria for ordering the results.
        Available options: 'downloads', 'likes', 'created', 'modified'.
        """,
        examples=["downloads", "likes", "created", "modified"],
    )
    # TODO: Add direction field if needed


class HuggingFaceImportModelReq(BaseRequestModel):
    """Request for importing a HuggingFace model to storage."""

    model: ModelTarget = Field(
        description="""
        Target model to import from HuggingFace.
        Contains the model ID and optional revision to specify which version to import.
        """,
        examples=[
            {"model_id": "microsoft/DialoGPT-medium", "revision": "main"},
            {"model_id": "openai/gpt-2", "revision": "v1.0"},
        ],
    )
    registry_name: str = Field(
        description="""
        Name of the HuggingFace registry to import from.
        This should match the configured registry name in the system.
        """,
        examples=["huggingface", "my-huggingface-registry"],
    )
    storage_name: str = Field(
        description="""
        Target storage name where the model will be imported.
        Must be a configured and accessible storage backend.
        """,
        examples=["default-minio", "s3-storage", "local-storage"],
    )
    bucket_name: str = Field(
        description="""
        Target bucket name within the storage.
        The bucket must exist and be writable by the service.
        """,
        examples=["models", "huggingface-models", "ai-models"],
    )


class HuggingFaceImportModelsBatchReq(BaseRequestModel):
    """Request for batch importing multiple HuggingFace models to storage."""

    models: list[ModelTarget] = Field(
        description="""
        List of models to import from HuggingFace.
        Each model must specify the model ID and optional revision.
        """,
        examples=[
            [
                {"model_id": "microsoft/DialoGPT-medium", "revision": "main"},
                {"model_id": "openai/gpt-2", "revision": "v1.0"},
            ]
        ],
    )
    registry_name: str = Field(
        description="""
        Name of the HuggingFace registry to import from.
        This should match the configured registry name in the system.
        """,
        examples=["huggingface", "my-huggingface-registry"],
    )
    storage_name: str = Field(
        description="""
        Target storage name where all models will be imported.
        Must be a configured and accessible storage backend.
        """,
        examples=["default-minio", "s3-storage", "local-storage"],
    )
    bucket_name: str = Field(
        description="""
        Target bucket name within the storage for all models.
        The bucket must exist and be writable by the service.
        """,
        examples=["models", "huggingface-models", "ai-models"],
    )


class HuggingFaceImportTaskStatusReq(BaseRequestModel):
    """Request for getting the status of a HuggingFace scan job."""

    task_id: str = Field(
        description="""
        ID of the import job to check status for.
        This ID is returned when starting a scan operation.
        """,
        examples=["550e8400-e29b-41d4-a716-446655440000", "123e4567-e89b-12d3-a456-426614174000"],
    )
