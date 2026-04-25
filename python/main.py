import cv2
import numpy as np
import time
import threading
import base64
import os
import glob
from arduino.app_utils import App
from arduino.app_bricks.web_ui import WebUI

# --- CONFIGURATION ---
TEST_DELAY = 3        # Seconds for testing (Change to 900 for real use)
SENSITIVITY = 40      # How 'different' a pixel must be to count (0-255)
ALARM_THRESHOLD = 500 # How many changed pixels trigger an alarm
# ---------------------

ui = WebUI()
state_lock = threading.Lock()
monitor_config = {
    "test_delay": TEST_DELAY,
    "sensitivity": SENSITIVITY,
    "alarm_threshold": ALARM_THRESHOLD,
}
monitor_status = {
    "status": "starting",
    "message": "Monitor is starting...",
}
last_update = None
rebaseline_requested = False


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def update_config(key, value):
    with state_lock:
        monitor_config[key] = value


def get_config():
    with state_lock:
        return dict(monitor_config)


def request_rebaseline():
    global rebaseline_requested
    with state_lock:
        rebaseline_requested = True


def consume_rebaseline_request():
    global rebaseline_requested
    with state_lock:
        requested = rebaseline_requested
        rebaseline_requested = False
        return requested


def set_status(status, message):
    with state_lock:
        monitor_status["status"] = status
        monitor_status["message"] = message


def get_status():
    with state_lock:
        return dict(monitor_status)


def set_last_update(update):
    global last_update
    with state_lock:
        last_update = dict(update)


def get_last_update():
    with state_lock:
        return dict(last_update) if last_update else None


def on_get_status(_sid, _payload):
    status_payload = get_status()
    ui.send_message("monitor_status", message={
        "status": status_payload.get("status"),
        "message": status_payload.get("message"),
        "config": get_config(),
    })

    latest = get_last_update()
    if latest:
        ui.send_message("pollen_update", message=latest)


def on_set_sensitivity(_sid, value):
    try:
        update_config("sensitivity", int(clamp(float(value), 0, 255)))
    except Exception:
        pass


def on_set_alarm_threshold(_sid, value):
    try:
        update_config("alarm_threshold", int(clamp(float(value), 1, 1000000)))
    except Exception:
        pass


def on_set_test_delay(_sid, value):
    try:
        update_config("test_delay", float(clamp(float(value), 0.5, 3600)))
    except Exception:
        pass


ui.on_message("set_sensitivity", on_set_sensitivity)
ui.on_message("set_alarm_threshold", on_set_alarm_threshold)
ui.on_message("set_test_delay", on_set_test_delay)
ui.on_message("rebaseline", lambda _sid, _message: request_rebaseline())
ui.on_message("get_status", on_get_status)

def capture_frame(cap):
    ret, frame = cap.read()
    if not ret:
        print("Error: Could not grab image.")
        return None
    return frame


def encode_frame_to_data_url(frame):
    ok, buffer = cv2.imencode('.jpg', frame)
    if not ok:
        return None
    encoded = base64.b64encode(buffer.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def list_video_devices():
    return sorted(glob.glob("/dev/video*"))


def candidate_camera_indices():
    preferred = os.getenv("CAMERA_INDEX")
    candidates = []

    if preferred is not None:
        try:
            candidates.append(int(preferred))
        except ValueError:
            pass

    candidates.extend([0, 1, 2, 3, 4])

    # Keep order, remove duplicates
    unique = []
    for idx in candidates:
        if idx not in unique:
            unique.append(idx)
    return unique


def open_camera_capture():
    backends = [None]
    if hasattr(cv2, "CAP_V4L2"):
        backends.append(cv2.CAP_V4L2)

    for index in candidate_camera_indices():
        for backend in backends:
            cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            if cap.isOpened():
                # Warm-up read to ensure stream is alive
                ok, _ = cap.read()
                if ok:
                    print(f"Using camera index {index} with backend {backend}")
                    return cap
            cap.release()

    return None

def pollen_monitor_loop():
    cap = None
    while cap is None:
        cap = open_camera_capture()
        if cap is None:
            devices = list_video_devices()
            device_text = ", ".join(devices) if devices else "none"
            msg = f"Camera not ready. Retrying... Detected devices: {device_text}"
            set_status("error", msg)
            ui.send_message("monitor_status", message={
                "status": "error",
                "message": msg,
                "config": get_config(),
            })
            time.sleep(2)
    
    # 1. INITIALIZATION: Capture the "Clean" state
    print("--- POLLEN MONITOR INITIALIZING ---")
    print("Step 1: Taking 'Clean' photo in 2 seconds...")
    time.sleep(2)
    base_frame = capture_frame(cap)
    if base_frame is None:
        set_status("error", "Failed to capture initial baseline frame.")
        ui.send_message("monitor_status", message={
            "status": "error",
            "message": "Failed to capture initial baseline frame.",
            "config": get_config(),
        })
        cap.release()
        return
        
    base_gray = cv2.cvtColor(base_frame, cv2.COLOR_BGR2GRAY)
    print("Base image captured. Starting loop...")
    set_status("running", "Baseline captured. Monitoring started.")
    ui.send_message("monitor_status", message={
        "status": "running",
        "message": "Baseline captured. Monitoring started.",
        "config": get_config(),
    })

    try:
        while True:
            config = get_config()

            if consume_rebaseline_request():
                print("Taking new baseline...")
                fresh_base = capture_frame(cap)
                if fresh_base is not None:
                    base_gray = cv2.cvtColor(fresh_base, cv2.COLOR_BGR2GRAY)
                    set_status("running", "New baseline captured successfully.")
                    ui.send_message("monitor_status", message={
                        "status": "running",
                        "message": "New baseline captured successfully.",
                        "config": config,
                    })

            # 2. WAIT
            time.sleep(config["test_delay"])

            # 3. CAPTURE CURRENT IMAGE
            current_frame = capture_frame(cap)
            if current_frame is None:
                cap.release()
                cap = None
                while cap is None:
                    cap = open_camera_capture()
                    if cap is None:
                        msg = "Camera stream lost. Retrying..."
                        set_status("error", msg)
                        ui.send_message("monitor_status", message={
                            "status": "error",
                            "message": msg,
                            "config": get_config(),
                        })
                        time.sleep(2)
                set_status("running", "Camera stream recovered.")
                ui.send_message("monitor_status", message={
                    "status": "running",
                    "message": "Camera stream recovered.",
                    "config": get_config(),
                })
                continue
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)

            # 4. SUBTRACTION (Technique B)
            # Calculate the absolute difference between base and current
            diff = cv2.absdiff(base_gray, current_gray)
            
            # Apply threshold to create a black and white "Pollen Map"
            _, pollen_map = cv2.threshold(diff, config["sensitivity"], 255, cv2.THRESH_BINARY)

            # 5. COUNT PIXELS
            pollen_score = int(np.sum(pollen_map == 255))
            
            # 6. RESULTS
            timestamp = time.strftime('%H:%M:%S')
            print(f"[{timestamp}] Pollen Score: {pollen_score}")
            is_alert = pollen_score > config["alarm_threshold"]
            
            if is_alert:
                print(">>> WARNING: POLLEN ACCUMULATION DETECTED! <<<")

            frame_data_url = encode_frame_to_data_url(current_frame)
                
            # Send message to UI
            ui.send_message("pollen_update", message={
                "score": pollen_score, 
                "timestamp": timestamp, 
                "isAlert": is_alert,
                "config": config,
                "frame": frame_data_url,
            })
            set_last_update({
                "score": pollen_score,
                "timestamp": timestamp,
                "isAlert": is_alert,
                "config": config,
                "frame": frame_data_url,
            })

    except Exception as e:
        print(f"Monitor stopped: {e}")
        set_status("error", str(e))
        ui.send_message("monitor_status", message={
            "status": "error",
            "message": str(e),
            "config": get_config(),
        })
    finally:
        cap.release()

# Start the OpenCV monitor in a daemon thread so it runs in the background
thread = threading.Thread(target=pollen_monitor_loop, daemon=True)
thread.start()

# Let the Arduino App Lab take over the main thread and run the app
App.run()
