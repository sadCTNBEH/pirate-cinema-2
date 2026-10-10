from pydantic import BaseModel


class StatusResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    detail: str
