"""CCTV -> detection -> event pipeline.

Reads a video (file or RTSP/webcam index), tracks people with
YOLOv8 + ByteTrack, and emits ENTRY/EXIT events across a configurable
counting line to both a local JSONL log and the Store Intelligence
API (idempotent ingestion, so re-runs / retries are safe).

Usage:
    python pipeline.py --video path/to/video.mp4 --store STORE_1 --camera CAM3_ENTRY --line-x 1180
    python pipeline.py --video 0 --headless                # webcam, no display window
    python pipeline.py --video rtsp://... --api-url http://api:8000

Design notes: see docs/CHOICES.md.
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import requests
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store Intelligence detection pipeline")
    parser.add_argument("--video", required=True, help="Video file path, RTSP URL, or webcam index (e.g. 0)")
    parser.add_argument("--store", default="STORE_1", help="Store ID")
    parser.add_argument("--camera", default="CAM3_ENTRY", help="Camera ID")
    parser.add_argument("--line-x", type=int, default=1180, help="X pixel coordinate of the counting line")
    parser.add_argument("--model", default="yolov8n.pt", help="Path to YOLO weights")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Base URL of the Store Intelligence API")
    parser.add_argument("--event-file", default="events.jsonl", help="Path to local event log")
    parser.add_argument("--headless", action="store_true", help="Run without opening a display window")
    parser.add_argument("--min-frame-gap", type=int, default=30, help="Min frames between re-firing an event for the same track")
    parser.add_argument("--conf", type=float, default=0.25, help="Detection confidence threshold")
    return parser.parse_args()


def resolve_video_source(video: str) -> str | int:
    # allow "0", "1" etc. to mean a webcam index
    if video.isdigit():
        return int(video)
    return video


class EventEmitter:
    def __init__(self, store_id: str, camera_id: str, api_url: str, event_file: str) -> None:
        self.store_id = store_id
        self.camera_id = camera_id
        self.api_url = api_url.rstrip("/")
        self.event_file = Path(event_file)

    def emit(self, visitor_id: int, event_type: str, queue_depth: int | None = None) -> None:
        event = {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "visitor_id": f"VIS_{visitor_id}",
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.90,
            "metadata": {"queue_depth": queue_depth, "session_seq": 1},
        }

        with self.event_file.open("a") as f:
            f.write(json.dumps(event) + "\n")

        try:
            response = requests.post(f"{self.api_url}/events/ingest", json=event, timeout=2)
            print(f"{event_type} | {event['visitor_id']} | API={response.status_code}")
        except requests.RequestException as exc:
            print(f"API error (event still logged locally): {exc}")


def run(args: argparse.Namespace) -> None:
    model = YOLO(args.model)
    source = resolve_video_source(args.video)
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        raise SystemExit(f"Could not open video source: {args.video}")

    emitter = EventEmitter(args.store, args.camera, args.api_url, args.event_file)

    previous_positions: dict[int, int] = {}
    last_event_frame: dict[int, int] = {}
    occupancy = 0
    frame_count = 0

    print(f"Starting pipeline | source={args.video} store={args.store} camera={args.camera} line_x={args.line_x}")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Video finished / stream ended.")
                break

            frame_count += 1

            results = model.track(
                frame, persist=True, tracker="bytetrack.yaml", conf=args.conf, verbose=False
            )

            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                ids = results[0].boxes.id.cpu().numpy()

                for box, raw_id in zip(boxes, ids):
                    x1, _, x2, _ = box
                    center_x = int((x1 + x2) / 2)
                    track_id = int(raw_id)

                    if track_id in previous_positions:
                        prev_x = previous_positions[track_id]
                        cooled_down = (
                            track_id not in last_event_frame
                            or frame_count - last_event_frame[track_id] > args.min_frame_gap
                        )

                        if prev_x > args.line_x and center_x <= args.line_x and cooled_down:
                            occupancy += 1
                            emitter.emit(track_id, "ENTRY")
                            last_event_frame[track_id] = frame_count
                        elif prev_x <= args.line_x and center_x > args.line_x and cooled_down:
                            occupancy = max(0, occupancy - 1)
                            emitter.emit(track_id, "EXIT")
                            last_event_frame[track_id] = frame_count

                    previous_positions[track_id] = center_x

            if not args.headless:
                annotated = results[0].plot()
                cv2.line(annotated, (args.line_x, 0), (args.line_x, annotated.shape[0]), (0, 255, 0), 3)
                cv2.putText(
                    annotated, f"Occupancy: {occupancy}", (20, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2,
                )
                cv2.imshow("Store Intelligence", annotated)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()
        print("Done.")


if __name__ == "__main__":
    run(parse_args())
