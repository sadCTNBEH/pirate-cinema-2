from enum import Enum


class VideoExtension(str, Enum):
    MKV = ".mkv"
    MP4 = ".mp4"
    AVI = ".avi"
    MOV = ".mov"
    WMV = ".wmv"
    FLV = ".flv"
    WEBM = ".webm"
    M4V = ".m4v"
    TS = ".ts"
    M2TS = ".m2ts"

    @classmethod
    def values(cls) -> set[str]:
        return {item.value for item in cls}