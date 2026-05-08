"""Helper-body response model — Java method bodies the resolver inlined."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HelperBody(BaseModel):
    """A helper method's source body, line-anchored to the file. Returned
    verbatim so a Business Analyst sees the actual delegation logic.
    """

    model_config = ConfigDict(frozen=True)

    fqn: str
    file: str
    start_line: int
    end_line: int
    signature: str
    body: str
    body_sha256: str
