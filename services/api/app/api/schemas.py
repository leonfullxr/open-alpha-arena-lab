from pydantic import BaseModel, ConfigDict


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(DTO):
    username: str
    password: str


class LoginOut(DTO):
    username: str
    role: str
