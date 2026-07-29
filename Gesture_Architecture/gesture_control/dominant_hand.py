"""
Left-dominant hand role mapping.

Right-dominant mapping (major=right, minor=left) remains in
``GestureController.classify_hands`` unchanged. This module adds a separate
left-dominant path so the default right-dominant structure is preserved.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict


def parse_mediapipe_hands(results):
    """
    Split MediaPipe hand results into physical left/right landmark sets.

    Returns (left_landmarks, right_landmarks); either may be None when only
    one hand is visible.
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

    return left, right


def classify_hands_left_dominant(controller_cls, results) -> None:
    """
    Map detected hands for left-dominant mode.

    Left hand becomes major (all primary gestures); right hand becomes minor
    (pinch scroll and secondary actions).
    """
    left, right = parse_mediapipe_hands(results)
    controller_cls.hr_major = left
    controller_cls.hr_minor = right


def zoom_index_landmarks_left_dominant(major_hand, minor_hand):
    """
    Index-finger landmarks for two-hand zoom when left hand is dominant.

    Physical left index comes from the major hand; physical right index from
    the minor hand.
    """
    return major_hand.landmark[8], minor_hand.landmark[8]


def zoom_index_landmarks_right_dominant(major_hand, minor_hand):
    """
    Index-finger landmarks for two-hand zoom when right hand is dominant.

    Physical left index comes from the minor hand; physical right index from
    the major hand.
    """
    return minor_hand.landmark[8], major_hand.landmark[8]
