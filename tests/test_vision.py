"""Pruebas de los contratos y la coordinación del sistema de visión."""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

import numpy as np

from clases.controlador_modelo import YOLOModelController
from clases.coordinador_vision import VisionCoordinator
from clases.deteccion import (
    BoundingBox,
    DetectedObject,
    DetectionEvent,
    DetectionResult,
)


class FakeVideoSource:
    def __init__(self, frame: np.ndarray) -> None:
        self.frames = [frame]
        self.reads = 0
        self.closed = False

    def read(self) -> np.ndarray:
        frame = self.frames[min(self.reads, len(self.frames) - 1)]
        self.reads += 1
        return frame

    def close(self) -> None:
        self.closed = True


class FakeDetector:
    def __init__(self, result: DetectionResult) -> None:
        self.result = result
        self.calls = 0

    def detect(self, _: np.ndarray) -> DetectionResult:
        self.calls += 1
        return self.result


class FakeDisplay:
    def __init__(self, frames_before_close: int) -> None:
        self.frames_before_close = frames_before_close
        self.frames_shown = 0
        self.shown_frames: list[np.ndarray] = []
        self.closed = False

    def show(self, frame: np.ndarray) -> None:
        self.frames_shown += 1
        self.shown_frames.append(frame)

    def should_close(self) -> bool:
        return self.frames_shown >= self.frames_before_close

    def close(self) -> None:
        self.closed = True


class FakeListener:
    def __init__(self) -> None:
        self.events: list[DetectionEvent] = []

    def on_detection(self, event: DetectionEvent) -> None:
        self.events.append(event)


class DetectionEventTests(unittest.TestCase):
    def test_event_serializes_detection_data(self) -> None:
        event = DetectionEvent(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            frame_width=640,
            frame_height=480,
            objects=(
                DetectedObject(
                    label="bus",
                    confidence=0.9,
                    bounding_box=BoundingBox(1, 2, 30, 40),
                ),
            ),
        )

        payload = event.to_dict()

        self.assertEqual(payload["frame_width"], 640)
        self.assertEqual(payload["objects"][0]["label"], "bus")
        self.assertEqual(
            payload["objects"][0]["bounding_box"],
            {"x1": 1, "y1": 2, "x2": 30, "y2": 40},
        )


class YOLOModelControllerTests(unittest.TestCase):
    def test_converts_model_output_to_detection_event(self) -> None:
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        boxes = MagicMock()
        boxes.xyxy.cpu.return_value.tolist.return_value = [[1, 2, 15, 9]]
        boxes.conf.cpu.return_value.tolist.return_value = [0.9]
        boxes.cls.cpu.return_value.tolist.return_value = [0]
        model_result = MagicMock()
        model_result.boxes = boxes
        model_result.names = {0: "bus"}
        model_result.plot.return_value = frame
        model = MagicMock()
        model.predict.return_value = [model_result]
        model_path = Path(__file__).resolve().parents[1] / "modelos" / "yolo11n.pt"

        with patch("clases.controlador_modelo.YOLO", return_value=model):
            controller = YOLOModelController(model_path)
            result = controller.detect(frame)

        self.assertEqual(result.event.frame_width, 20)
        self.assertEqual(result.event.frame_height, 10)
        self.assertEqual(len(result.event.objects), 1)
        self.assertEqual(result.event.objects[0].label, "bus")
        self.assertEqual(result.event.objects[0].confidence, 0.9)
        self.assertIs(result.annotated_frame, frame)


class VisionCoordinatorTests(unittest.TestCase):
    def test_publishes_detection_and_closes_components(self) -> None:
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        event = DetectionEvent(
            timestamp=datetime.now(timezone.utc),
            frame_width=20,
            frame_height=10,
            objects=(),
        )
        result = DetectionResult(event=event, annotated_frame=frame)
        source = FakeVideoSource(frame)
        detector = FakeDetector(result)
        display = FakeDisplay(frames_before_close=1)
        listener = FakeListener()
        coordinator = VisionCoordinator(
            video_source=source,
            detector=detector,
            display=display,
            listeners=(listener,),
        )

        coordinator.run()

        self.assertEqual(detector.calls, 1)
        self.assertEqual(listener.events, [event])
        self.assertTrue(source.closed)
        self.assertTrue(display.closed)

    def test_keeps_last_annotated_frame_between_detections(self) -> None:
        first_frame = np.zeros((10, 20, 3), dtype=np.uint8)
        next_frame = np.ones((10, 20, 3), dtype=np.uint8)
        annotated_frame = np.full((10, 20, 3), 2, dtype=np.uint8)
        event = DetectionEvent(
            timestamp=datetime.now(timezone.utc),
            frame_width=20,
            frame_height=10,
            objects=(),
        )
        source = FakeVideoSource(first_frame)
        source.frames.append(next_frame)
        detector = FakeDetector(DetectionResult(event, annotated_frame))
        display = FakeDisplay(frames_before_close=2)
        coordinator = VisionCoordinator(
            video_source=source,
            detector=detector,
            display=display,
            detection_interval=60,
        )

        coordinator.run()

        self.assertEqual(detector.calls, 1)
        self.assertIs(display.shown_frames[0], annotated_frame)
        self.assertIs(display.shown_frames[1], annotated_frame)

    def test_closes_components_when_listener_fails(self) -> None:
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        event = DetectionEvent(
            timestamp=datetime.now(timezone.utc),
            frame_width=20,
            frame_height=10,
            objects=(),
        )
        source = FakeVideoSource(frame)
        display = FakeDisplay(frames_before_close=1)

        class FailingListener:
            def on_detection(self, _: DetectionEvent) -> None:
                raise ValueError("listener failure")

        coordinator = VisionCoordinator(
            video_source=source,
            detector=FakeDetector(DetectionResult(event, frame)),
            display=display,
            listeners=(FailingListener(),),
        )

        with self.assertRaisesRegex(ValueError, "listener failure"):
            coordinator.run()

        self.assertTrue(source.closed)
        self.assertTrue(display.closed)

    def test_stops_when_external_event_is_set(self) -> None:
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        event = DetectionEvent(
            timestamp=datetime.now(timezone.utc),
            frame_width=20,
            frame_height=10,
            objects=(),
        )
        source = FakeVideoSource(frame)
        display = FakeDisplay(frames_before_close=100)
        stop_event = Event()
        stop_event.set()
        coordinator = VisionCoordinator(
            video_source=source,
            detector=FakeDetector(DetectionResult(event, frame)),
            display=display,
        )

        coordinator.run(stop_event=stop_event)

        self.assertEqual(source.reads, 0)
        self.assertTrue(source.closed)
        self.assertTrue(display.closed)


if __name__ == "__main__":
    unittest.main()
