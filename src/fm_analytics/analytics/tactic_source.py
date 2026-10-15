"""Provenance for a published tactic; the original FM file is authoritative."""

from dataclasses import dataclass
from pathlib import PurePath
import re
from urllib.parse import urlparse


@dataclass(frozen=True)
class TacticSource:
    author: str
    url: str
    download_url: str
    filename: str
    sha256: str
    verification: str

    def __post_init__(self) -> None:
        for value in (self.author, self.verification):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("tactic source needs an author and verification description")
        for value in (self.url, self.download_url):
            if not isinstance(value, str) or urlparse(value).scheme != "https" or not urlparse(value).netloc:
                raise ValueError("tactic source links must be HTTPS URLs")
        if (
            not isinstance(self.filename, str) or not re.fullmatch(r"[a-z0-9_]+\.fmf", self.filename)
            or PurePath(self.filename).name != self.filename
        ):
            raise ValueError("tactic source filename must be a simple .fmf filename")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("tactic source sha256 must be a SHA-256 hex digest")


def source_from_json(value, *, only_known_keys) -> TacticSource | None:
    if value is None:
        return None
    keys = {"author", "url", "downloadUrl", "filename", "sha256", "verification"}
    if not isinstance(value, dict):
        raise ValueError("tactic source must be an object")
    only_known_keys(value, frozenset(keys), "tactic source")
    if set(value) != keys:
        raise ValueError("tactic source must specify author, links, filename, sha256 and verification")
    return TacticSource(
        value["author"], value["url"], value["downloadUrl"], value["filename"],
        value["sha256"], value["verification"],
    )
