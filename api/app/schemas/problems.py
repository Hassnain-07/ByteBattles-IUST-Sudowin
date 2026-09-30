from pydantic import BaseModel, Field, field_validator
from typing import Dict, List

from shared.models import Difficulty

import re

SLUG_REGEX = r"^[a-z0-9]+(-[a-z0-9]+)*$"

class ProblemResponse(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    accepted_submissions: int

class ProblemDetailResponse(ProblemResponse):
    description: str
    constraints: List[str]
    input_desc: str
    output_desc: str
    sample_io: Dict[str, str]
    explanation: str | None

    memory_limit_mb: int
    time_limit_sec: int

    source: str | None
    editorial: str | None
    visibility: bool

class ProblemArrayDataValidator(BaseModel):
    tags: List[str]
    constraints: List[str]
    sample_io: Dict[str, str]

class TagCreate(BaseModel):
    name: str
    slug: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Tag name cannot be empty")
        return v

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v):
        if len(v) > 50 or not re.match(SLUG_REGEX, v):
            raise ValueError(
                "Slug must be 1-50 lowercase letters, numbers or hyphens"
            )
        return v

class ProblemCreateResponse(BaseModel):
    id: str
    title: str
    difficulty: Difficulty
    tags: List[str]
    testcases: int
class TagResponse(BaseModel):
    name: str
    slug: str

    model_config = {
        "from_attributes": True
    }

class ProblemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    difficulty: Difficulty | None = None
    constraints: List[str] | None = None
    tags: List[str] | None = None
    sample_io: Dict[str, str] | None = None

    input_desc: str | None = None
    output_desc: str | None = None
    explanation: str | None = None

    memory_limit_mb: int | None = Field(default=None, gt=0)
    time_limit_sec: int | None = Field(default=None, gt=0)

    visibility: bool | None = None
    source: str | None = None
    editorial: str | None = None

class RejudgeResponse(BaseModel):
    problem_id: str
    requeued: int
