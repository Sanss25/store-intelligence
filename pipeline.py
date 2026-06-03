import cv2
import json
import uuid
import requests
from datetime import datetime, UTC
from ultralytics import YOLO

# ==========================
# CONFIG
# ==========================

VIDEO_PATH = r"C:\Users\Lenovo\Downloads\Store 1-20260602T101818Z-3-001ec38db8\Store 1\CAM 3 - entry.mp4"

STORE_ID = "STORE_1"
CAMERA_ID = "CAM3_ENTRY"

LINE_X = 1180
EVENT_FILE = "events.jsonl"

# ==========================
# LOAD MODEL
# ==========================

model = YOLO("yolov8n.pt")

# ==========================
# OPEN VIDEO
# ==========================

cap = cv2.VideoCapture(VIDEO_PATH)

if not cap.isOpened():
    print("ERROR: Could not open video")
    exit()

# ==========================
# STATE
# ==========================

previous_positions = {}
occupancy = 0
last_event_frame = {}
frame_count = 0

# ==========================
# EVENT FUNCTION
# ==========================

def emit_event(visitor_id, event_type):

    event = {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": CAMERA_ID,
        "visitor_id": f"VIS_{visitor_id}",
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "zone_id": None,
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.90,
        "metadata": {
            "queue_depth": None,
            "session_seq": 1
        }
    }

    # Save locally
    with open(EVENT_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")

    # Send to API
    try:
        response = requests.post(
            "http://127.0.0.1:8000/events/ingest",
            json={
                "event_id": event["event_id"],
                "store_id": event["store_id"],
                "camera_id": event["camera_id"],
                "visitor_id": event["visitor_id"],
                "event_type": event["event_type"],
                "timestamp": event["timestamp"]
            },
            timeout=2
        )

        print(
            f"{event_type} | VIS_{visitor_id} | API={response.status_code}"
        )

    except Exception as e:
        print("API Error:", e)

# ==========================
# MAIN LOOP
# ==========================

print("Starting...")

while True:

    ret, frame = cap.read()

    if not ret:
        print("Video Finished")
        break

    frame_count += 1

    results = model.track(
        frame,
        persist=True,
        tracker="bytetrack.yaml",
        conf=0.25,
        verbose=False
    )

    annotated = results[0].plot()

    # Draw counting line
    cv2.line(
        annotated,
        (LINE_X, 0),
        (LINE_X, annotated.shape[0]),
        (0, 255, 0),
        3
    )

    if results[0].boxes.id is not None:

        boxes = results[0].boxes.xyxy.cpu().numpy()
        ids = results[0].boxes.id.cpu().numpy()

        for box, track_id in zip(boxes, ids):

            x1, y1, x2, y2 = box

            center_x = int((x1 + x2) / 2)

            track_id = int(track_id)

            if track_id in previous_positions:

                prev_x = previous_positions[track_id]

                # ENTRY
                if prev_x > LINE_X and center_x <= LINE_X:

                    if (
                        track_id not in last_event_frame
                        or frame_count - last_event_frame[track_id] > 30
                    ):

                        occupancy += 1

                        emit_event(track_id, "ENTRY")

                        last_event_frame[track_id] = frame_count

                # EXIT
                elif prev_x <= LINE_X and center_x > LINE_X:

                    if (
                        track_id not in last_event_frame
                        or frame_count - last_event_frame[track_id] > 30
                    ):

                        occupancy = max(0, occupancy - 1)

                        emit_event(track_id, "EXIT")

                        last_event_frame[track_id] = frame_count

            previous_positions[track_id] = center_x

    cv2.putText(
        annotated,
        f"Occupancy: {occupancy}",
        (20, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2
    )

    cv2.imshow("Store Analytics", annotated)

    if cv2.waitKey(1) & 0xFF == 27:
        break

# ==========================
# CLEANUP
# ==========================

cap.release()
cv2.destroyAllWindows()

print("Done.")