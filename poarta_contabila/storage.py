"""Bucket (ARCHITECTURE §4): sources, packages, exports. S3-compatible, keys as given."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class S3Config:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "auto"

    @classmethod
    def from_env(cls) -> S3Config | None:
        """``S3_ENDPOINT`` / ``S3_ACCESS_KEY`` / ``S3_SECRET_KEY`` / ``S3_BUCKET``, or None."""
        keys = ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET")
        values = [os.environ.get(k) for k in keys]
        if not all(values):
            return None
        return cls(*values, region=os.environ.get("S3_REGION", "auto"))


class S3BlobStore:
    """BlobStore on an S3 bucket. *client* may be injected (tests)."""

    def __init__(self, config: S3Config, client: Any | None = None) -> None:
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=config.endpoint,
                aws_access_key_id=config.access_key,
                aws_secret_access_key=config.secret_key,
                region_name=config.region,
            )
        self._s3, self._bucket = client, config.bucket

    def put(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
