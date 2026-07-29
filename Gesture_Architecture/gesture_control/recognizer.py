import math

from .enums import Gest, HLabel


class HandRecog:
    """
    Convert MediaPipe landmarks into discrete gesture labels.

    This class is rule-based (geometry + thresholds), not a learned classifier.
    MediaPipe provides 21 landmarks per hand; we compute distances/ratios and
    map them to gesture enums with temporal smoothing.
    """

    def __init__(self, hand_label):
        self.finger = 0
        self.ori_gesture = Gest.PALM
        self.prev_gesture = Gest.PALM
        self.frame_count = 0
        self.hand_result = None
        self.hand_label = hand_label

    def update_hand_result(self, hand_result):
        self.hand_result = hand_result

    def get_signed_dist(self, point):
        # Signed 2D distance: sign is based on y ordering.
        # Positive often indicates tip above lower joint in image coordinates.
        sign = -1
        if self.hand_result.landmark[point[0]].y < self.hand_result.landmark[point[1]].y:
            sign = 1
        dist = (self.hand_result.landmark[point[0]].x - self.hand_result.landmark[point[1]].x) ** 2
        dist += (self.hand_result.landmark[point[0]].y - self.hand_result.landmark[point[1]].y) ** 2
        dist = math.sqrt(dist)
        return dist * sign

    def get_dist(self, point):
        # Plain Euclidean distance in normalized landmark coordinates.
        dist = (self.hand_result.landmark[point[0]].x - self.hand_result.landmark[point[1]].x) ** 2
        dist += (self.hand_result.landmark[point[0]].y - self.hand_result.landmark[point[1]].y) ** 2
        dist = math.sqrt(dist)
        return dist

    def get_dz(self, point):
        # Relative depth separation between two landmarks.
        return abs(self.hand_result.landmark[point[0]].z - self.hand_result.landmark[point[1]].z)

    def _is_thumb_extended(self) -> bool:
        if self.hand_result is None:
            return False
        tip = self.hand_result.landmark[4]
        ip = self.hand_result.landmark[3]
        return tip.y < ip.y - 0.02

    def _is_pinky_extended(self) -> bool:
        if self.hand_result is None:
            return False
        return self.hand_result.landmark[20].y < self.hand_result.landmark[18].y - 0.02

    def _are_index_middle_ring_folded(self) -> bool:
        if self.hand_result is None:
            return False
        for tip_id, pip_id in ((8, 6), (12, 10), (16, 14)):
            if self.hand_result.landmark[tip_id].y < self.hand_result.landmark[pip_id].y:
                return False
        return True

    def _is_call_sign_pose(self) -> bool:
        """Thumb and pinky extended; index, middle, ring folded (shaka / call sign)."""
        return (
            self._is_thumb_extended()
            and self._is_pinky_extended()
            and self._are_index_middle_ring_folded()
        )

    def set_finger_state(self):
        """
        Build binary finger-state encoding for index/middle/ring/pinky.

        For each finger:
        ratio = signed_dist(tip, mid_joint) / signed_dist(mid_joint, base_joint)
        ratio > 0.5  -> finger considered open (bit 1)
        else         -> finger considered closed (bit 0)
        """
        if self.hand_result is None:
            return

        # Landmark ids (MediaPipe Hands):
        # index: tip=8, pip/mcp region=5
        # middle: tip=12, base region=9
        # ring: tip=16, base region=13
        # pinky: tip=20, base region=17
        points = [[8, 5, 0], [12, 9, 0], [16, 13, 0], [20, 17, 0]]
        self.finger = 0
        self.finger = self.finger | 0  # thumb
        for point in points:
            dist = self.get_signed_dist(point[:2])
            dist2 = self.get_signed_dist(point[1:])

            try:
                ratio = round(dist / dist2, 1)
            except Exception:
                ratio = round(dist2 / 0.01, 1)

            self.finger = self.finger << 1
            if ratio > 0.5:
                self.finger = self.finger | 1

    def get_gesture(self):
        """
        Convert current finger encoding + landmark checks into final gesture enum.

        Special gestures:
        - pinch: thumb tip (4) near index tip (8)
        - V gesture: index-middle spread ratio high
        - two-finger-closed: index-middle close in depth

        Temporal smoothing:
        gesture must remain stable for multiple frames before being committed.
        """
        if self.hand_result is None:
            return Gest.PALM

        current_gesture = Gest.PALM

        if self.hand_label == HLabel.MAJOR and self._is_call_sign_pose():
            current_gesture = Gest.THUMBS_UP
        elif self.finger in [Gest.LAST3, Gest.LAST4] and self.get_dist([8, 4]) < 0.05:
            if self.hand_label == HLabel.MINOR:
                current_gesture = Gest.PINCH_MINOR
            else:
                current_gesture = Gest.PINCH_MAJOR

        elif Gest.FIRST2 == self.finger:
            point = [[8, 12], [5, 9]]
            dist1 = self.get_dist(point[0])
            dist2 = self.get_dist(point[1])
            ratio = dist1 / dist2
            if ratio > 1.7:
                current_gesture = Gest.V_GEST
            else:
                if self.get_dz([8, 12]) < 0.1:
                    current_gesture = Gest.TWO_FINGER_CLOSED
                else:
                    current_gesture = Gest.MID
        else:
            current_gesture = self.finger

        if current_gesture == self.prev_gesture:
            self.frame_count += 1
        else:
            self.frame_count = 0

        self.prev_gesture = current_gesture

        # Commit only if stable enough to reduce frame-to-frame jitter.
        if self.frame_count > 4:
            self.ori_gesture = current_gesture
        return self.ori_gesture
