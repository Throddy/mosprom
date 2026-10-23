from core.schemas import CameraConfig


def load_cameras(path: str) -> list[CameraConfig]:
    raise NotImplementedError("BE-1")


def save_cameras(path: str, cameras: list[CameraConfig]) -> None:
    raise NotImplementedError("BE-1")
