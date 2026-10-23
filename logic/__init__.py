from core.schemas import CameraConfig, Detection, Event, Track


class Engine:
    def __init__(self, cameras: list[CameraConfig]) -> None:
        raise NotImplementedError("BE-4")

    def process(self, camera_id: str, ts: float, frame_size: tuple[int, int],
                detections: list[Detection]) -> list[Event]:
        raise NotImplementedError("BE-4")

    def update_camera(self, camera: CameraConfig) -> None:
        raise NotImplementedError("BE-4")

    def tracks(self, camera_id: str) -> list[Track]:
        raise NotImplementedError("BE-4")


def rule_specs() -> list[dict]:
    raise NotImplementedError("BE-4")
