from core.schemas import CameraConfig, Detection, Event, Track


class Engine:
    def __init__(self, cameras: list[CameraConfig]) -> None:
        raise NotImplementedError("LOG-1")

    def process(self, camera_id: str, ts: float, frame_size: tuple[int, int],
                detections: list[Detection]) -> list[Event]:
        raise NotImplementedError("LOG-1")

    def update_camera(self, camera: CameraConfig) -> None:
        raise NotImplementedError("LOG-1")

    def tracks(self, camera_id: str) -> list[Track]:
        raise NotImplementedError("LOG-1")


def rule_specs() -> list[dict]:
    raise NotImplementedError("LOG-1")
