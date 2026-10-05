from pydantic import BaseModel


class PlayRequest(BaseModel):
    hash: str
    file_id: int
    file_name: str
    start_time: int = 0


class NextRequest(BaseModel):
    hash: str
    file_id: int


class MagnetRequest(BaseModel):
    magnet: str
    title: str = ""