from __future__ import annotations

import time
from typing import Optional

import cv2
import mediapipe as mp
from google.protobuf.json_format import MessageToDict

from .controller import Controller
from .dominant_hand import (
    classify_hands_left_dominant,
    zoom_index_landmarks_left_dominant,
    zoom_index_landmarks_right_dominant,
)
from .enums import Gest, HLabel
from .gesture_audit import GestureAuditLogger
from .preview_stream import PreviewStream
from .recognizer import HandRecog

mp_drawing = mp.solutions.drawing_utils
mp_hands = mp.solutions.hands


class GestureController:
    """
    Runtime orchestrator for the full gesture pipeline.

    High-level data flow per frame:
    camera frame -> MediaPipe Hands landmarks -> HandRecog gesture enum ->
    Controller OS action -> optional landmark drawing for visualization.
    """

    gc_mode = 0
    cap = None
    CAM_HEIGHT = None
    CAM_WIDTH = None
    hr_major = None  # Right hand by default
    hr_minor = None  # Left hand by default
    dom_hand = True  # Right is major

    def __init__(self):
        # Open webcam (index 0). On Windows, CAP_DSHOW often starts faster and
        # avoids backend negotiation issues; fallback keeps portability.
        GestureController.gc_mode = 1
        GestureController.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not GestureController.cap.isOpened():
            # Fallback for systems where DirectShow backend is unavailable.
            GestureController.cap = cv2.VideoCapture(0)
        if GestureController.cap.isOpened():
            # Small buffer = lower capture latency. Moderate resolution keeps
            # MediaPipe + cursor control fast; preview is encoded separately.
            GestureController.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            GestureController.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            GestureController.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        GestureController.CAM_HEIGHT = GestureController.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        GestureController.CAM_WIDTH = GestureController.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        self.zoom_active = False
        self.prev_zoom_distance = None
        self.zoom_distance_threshold = 0.007

    @staticmethod
    def _finger_extended(hand_landmarks, tip_id, pip_id):
        return hand_landmarks.landmark[tip_id].y < hand_landmarks.landmark[pip_id].y

    @staticmethod
    def _finger_folded(hand_landmarks, tip_id, pip_id):
        return hand_landmarks.landmark[tip_id].y > hand_landmarks.landmark[pip_id].y

    def _is_two_hand_zoom_pose(self, hand_landmarks):
        return (
            self._finger_extended(hand_landmarks, 8, 6)
            and self._finger_folded(hand_landmarks, 12, 10)
            and self._finger_folded(hand_landmarks, 16, 14)
            and self._finger_folded(hand_landmarks, 20, 18)
        )

    def _update_two_hand_zoom(self, major_hand, minor_hand):
        if major_hand is None or minor_hand is None:
            self.zoom_active = False
            self.prev_zoom_distance = None
            return False

        major_ok = self._is_two_hand_zoom_pose(major_hand)
        minor_ok = self._is_two_hand_zoom_pose(minor_hand)
        if not (major_ok and minor_ok):
            self.zoom_active = False
            self.prev_zoom_distance = None
            return False

        if GestureController.dom_hand is True:
            left_idx, right_idx = zoom_index_landmarks_right_dominant(major_hand, minor_hand)
        else:
            left_idx, right_idx = zoom_index_landmarks_left_dominant(major_hand, minor_hand)
        distance = ((right_idx.x - left_idx.x) ** 2 + (right_idx.y - left_idx.y) ** 2) ** 0.5

        if not self.zoom_active:
            self.zoom_active = True
            self.prev_zoom_distance = distance
            return True

        delta = distance - self.prev_zoom_distance
        if abs(delta) > self.zoom_distance_threshold:
            # Closer fingers -> zoom out, farther fingers -> zoom in.
            Controller.apply_ctrl_zoom(zoom_in=(delta > 0))
            self.prev_zoom_distance = distance
        else:
            self.prev_zoom_distance = (self.prev_zoom_distance * 0.8) + (distance * 0.2)

        return True

    @staticmethod
    def classify_hands(results):
        """
        Split detected hands into left/right using MediaPipe handedness output.

        MediaPipe returns handedness as protobuf metadata aligned to each hand's
        landmarks. This function maps left/right into project roles:
        - major hand: primary pointer/control hand
        - minor hand: secondary hand (pinch scrolling priority)
        """
        left, right = None, None
        try:
            handedness_dict = MessageToDict(results.multi_handedness[0])
            if handedness_dict["classification"][0]["label"] == "Right":
                right = results.multi_hand_landmarks[0]
            else:
                left = results.multi_hand_landmarks[0]
        except Exception:
            pass

        try:
            handedness_dict = MessageToDict(results.multi_handedness[1])
            if handedness_dict["classification"][0]["label"] == "Right":
                right = results.multi_hand_landmarks[1]
            else:
                left = results.multi_hand_landmarks[1]
        except Exception:
            pass

        if GestureController.dom_hand is True:
            GestureController.hr_major = right
            GestureController.hr_minor = left
        else:
            GestureController.hr_major = left
            GestureController.hr_minor = right

    @staticmethod
    def apply_hand_classification(results):
        """
        Route hand-role assignment to the correct dominant-hand path.

        Right-dominant uses the existing ``classify_hands`` implementation.
        Left-dominant uses the separate module so default behavior is preserved.
        """
        if GestureController.dom_hand is True:
            GestureController.classify_hands(results)
        else:
            classify_hands_left_dominant(GestureController, results)

    @staticmethod
    def set_dominant_hand(hand: str) -> None:
        """Set preferred dominant hand: ``\"right\"`` (default) or ``\"left\"``."""
        GestureController.dom_hand = hand.strip().lower() != "left"

    def start(
        self,
        *,
        headless: bool = False,
        on_gesture_detected=None,
        on_frame=None,
        should_stop=None,
    ):
        """
        Run real-time loop:
        1) capture frame,
        2) infer 21 hand landmarks via MediaPipe,
        3) classify gesture from landmark geometry,
        4) execute mapped OS control action.

        headless: skip OpenCV preview window (desktop UI integration).
        on_gesture_detected: optional callback(label: str) when gesture action changes.
        on_frame: optional callback(jpeg_bytes) for UI live preview (headless).
        should_stop: optional callable returning True to end the loop.
        """
        preview_stream: Optional[PreviewStream] = None
        if headless and on_frame is not None:
            preview_stream = PreviewStream(on_frame)

        if GestureController.cap is None or not GestureController.cap.isOpened():
            raise RuntimeError(
                "Unable to open webcam (index 0). Close other camera apps, check camera permissions, "
                "or try another camera index."
            )

        handmajor = HandRecog(HLabel.MAJOR)
        handminor = HandRecog(HLabel.MINOR)
        audit = GestureAuditLogger()
        if headless:
            print("Gesture controller started (headless). Stop via API or UI.")
        else:
            print("Gesture controller started. Press Enter in the video window to exit.")
        print(f"Audit log: {audit.output_csv.resolve()}")

        last_ui_label = None

        # MediaPipe Hands settings:
        # - max_num_hands=2: track both hands for major/minor behaviors
        # - min_detection_confidence: confidence for initial palm/hand detection
        # - min_tracking_confidence: confidence for landmark tracking across frames
        with mp_hands.Hands(
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as hands:
            while GestureController.cap.isOpened() and GestureController.gc_mode:
                success, image = GestureController.cap.read()

                if not success:
                    print("Ignoring empty camera frame.")
                    continue

                # Mirror the frame for intuitive control (like a mirror view), then
                # convert BGR -> RGB because MediaPipe expects RGB input.
                image = cv2.cvtColor(cv2.flip(image, 1), cv2.COLOR_BGR2RGB)
                image.flags.writeable = False
                results = hands.process(image)

                image.flags.writeable = True
                # Convert back to BGR for OpenCV window rendering.
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

                if results.multi_hand_landmarks:
                    GestureController.apply_hand_classification(results)
                    handmajor.update_hand_result(GestureController.hr_major)
                    handminor.update_hand_result(GestureController.hr_minor)

                    recognition_start = time.perf_counter()
                    handmajor.set_finger_state()
                    handminor.set_finger_state()
                    zoom_consumed = self._update_two_hand_zoom(
                        handmajor.hand_result, handminor.hand_result
                    )
                    minor_gest = handminor.get_gesture()
                    major_gest = handmajor.get_gesture()
                    recognition_latency = time.perf_counter() - recognition_start

                    if zoom_consumed:
                        # Ensure drag/pinch states are released while zoom mode owns input.
                        Controller.handle_controls(Gest.PALM, handmajor.hand_result)
                    elif minor_gest == Gest.PINCH_MINOR:
                        Controller.handle_controls(minor_gest, handminor.hand_result)
                    elif major_gest == Gest.THUMBS_UP:
                        Controller.handle_controls(Gest.PALM, handmajor.hand_result)
                    else:
                        Controller.handle_controls(major_gest, handmajor.hand_result)

                    audit.record_frame(
                        zoom_consumed, minor_gest, major_gest, recognition_latency
                    )

                    ui_label = audit.event_label(
                        zoom_consumed,
                        audit.active_gesture(zoom_consumed, minor_gest, major_gest),
                    )
                    if ui_label and ui_label != last_ui_label:
                        last_ui_label = ui_label
                        if on_gesture_detected is not None:
                            try:
                                on_gesture_detected(ui_label, recognition_latency)
                            except TypeError:
                                try:
                                    on_gesture_detected(ui_label)
                                except Exception:
                                    pass
                            except Exception:
                                pass

                    if not headless:
                        for hand_landmarks in results.multi_hand_landmarks:
                            mp_drawing.draw_landmarks(
                                image, hand_landmarks, mp_hands.HAND_CONNECTIONS
                            )
                else:
                    # Reset cursor smoothing memory when no hand is visible.
                    Controller.prev_hand = None
                    self.zoom_active = False
                    self.prev_zoom_distance = None

                if preview_stream is not None:
                    preview_stream.submit(image)

                if not headless:
                    cv2.imshow("Gesture Controller", image)
                    if cv2.waitKey(5) & 0xFF == 13:
                        break
                else:
                    if preview_stream is not None:
                        # Match OpenCV window pacing so headless mode stays as smooth as main.py.
                        time.sleep(0.005)
                    if should_stop is not None and should_stop():
                        break

        if preview_stream is not None:
            preview_stream.close()

        GestureController.cap.release()
        if not headless:
            cv2.destroyAllWindows()
