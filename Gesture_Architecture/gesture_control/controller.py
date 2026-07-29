import time
from ctypes import POINTER, cast

import pyautogui
import screen_brightness_control as sbcontrol
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from .enums import Gest

pyautogui.FAILSAFE = False
# PyAutoGUI defaults to PAUSE=0.1s after every call; that stacks with moveTo's own
# duration and makes the cursor lag far behind the camera overlay. Set to 0 for
# real-time pointer control (clicks/scrolls stay responsive too).
pyautogui.PAUSE = 0


class Controller:
    """
    Execute OS actions mapped from recognized gestures.

    Design:
    - HandRecog decides "what gesture".
    - Controller decides "what action" on mouse/scroll/volume/brightness.
    - Class attributes keep state across frames (drag mode, pinch mode, etc.).
    """

    tx_old = 0
    ty_old = 0
    trial = True
    flag = False
    grabflag = False
    pinchmajorflag = False
    pinchminorflag = False
    pinchstartxcoord = None
    pinchstartycoord = None
    pinchdirectionflag = None
    prevpinchlv = 0
    pinchlv = 0
    framecount = 0
    prev_hand = None
    pinch_threshold = 0.3
    # Multiplier on damped pointer deltas in get_position (>1 feels faster / more
    # sensitive; 1.0 preserves the original curve). Does not change gesture rules.
    POINTER_GAIN = 1.25
    # Instant moves keep the OS cursor aligned with each processed frame; animated
    # moveTo(duration>0) trails behind the live hand overlay.
    POINTER_MOVE_DURATION = 0
    last_zoom_event_time = 0.0
    zoom_event_interval = 0.05

    @staticmethod
    def getpinchylv(hand_result):
        # Pinch displacement along y from the gesture start frame.
        return round((Controller.pinchstartycoord - hand_result.landmark[8].y) * 10, 1)

    @staticmethod
    def getpinchxlv(hand_result):
        # Pinch displacement along x from the gesture start frame.
        return round((hand_result.landmark[8].x - Controller.pinchstartxcoord) * 10, 1)

    @staticmethod
    def changesystembrightness():
        # Brightness adjustment is incremental and clamped to [0, 1].
        current_brightness = sbcontrol.get_brightness(display=0) / 100.0
        current_brightness += Controller.pinchlv / 50.0
        if current_brightness > 1.0:
            current_brightness = 1.0
        elif current_brightness < 0.0:
            current_brightness = 0.0
        sbcontrol.fade_brightness(
            int(100 * current_brightness), start=sbcontrol.get_brightness(display=0)
        )

    @staticmethod
    def changesystemvolume():
        # pycaw controls Windows master endpoint volume scalar [0, 1].
        devices = AudioUtilities.GetSpeakers()
        if devices is None:
            return
        # Newer pycaw: ``AudioDevice`` exposes ``EndpointVolume``; older builds
        # returned an ``IMMDevice`` and required ``Activate(IAudioEndpointVolume)``.
        if hasattr(devices, "EndpointVolume"):
            volume = devices.EndpointVolume
        else:
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
        current_volume = volume.GetMasterVolumeLevelScalar()
        current_volume += Controller.pinchlv / 50.0
        if current_volume > 1.0:
            current_volume = 1.0
        elif current_volume < 0.0:
            current_volume = 0.0
        volume.SetMasterVolumeLevelScalar(current_volume, None)

    @staticmethod
    def scrollVertical():
        # Positive pinch level -> scroll up; negative -> scroll down.
        pyautogui.scroll(120 if Controller.pinchlv > 0.0 else -120)

    @staticmethod
    def scrollHorizontal():
        # Horizontal scroll emulated through Shift+Ctrl + wheel on Windows apps.
        pyautogui.keyDown("shift")
        pyautogui.keyDown("ctrl")
        pyautogui.scroll(-120 if Controller.pinchlv > 0.0 else 120)
        pyautogui.keyUp("ctrl")
        pyautogui.keyUp("shift")

    @staticmethod
    def apply_ctrl_zoom(zoom_in):
        """
        Zoom the active app using Windows convention: Ctrl + mouse wheel.
        zoom_in=True sends wheel up, False sends wheel down.
        """
        now = time.monotonic()
        if now - Controller.last_zoom_event_time < Controller.zoom_event_interval:
            return
        Controller.last_zoom_event_time = now
        pyautogui.keyDown("ctrl")
        pyautogui.scroll(120 if zoom_in else -120)
        pyautogui.keyUp("ctrl")

    @staticmethod
    def get_position(hand_result):
        """
        Map hand landmark (id=9) to screen pointer with adaptive dampening.

        Small hand motion is suppressed; medium motion is smoothed; large motion
        is accelerated. This improves pointer stability and usability.
        """
        point = 9
        position = [hand_result.landmark[point].x, hand_result.landmark[point].y]
        sx, sy = pyautogui.size()
        x_old, y_old = pyautogui.position()
        x = int(position[0] * sx)
        y = int(position[1] * sy)
        if Controller.prev_hand is None:
            Controller.prev_hand = (x, y)
        delta_x = x - Controller.prev_hand[0]
        delta_y = y - Controller.prev_hand[1]

        distsq = delta_x**2 + delta_y**2
        ratio = 1
        Controller.prev_hand = [x, y]

        if distsq <= 25:
            ratio = 0
        elif distsq <= 900:
            ratio = 0.07 * (distsq ** (1 / 2))
        else:
            ratio = 2.1
        ratio *= Controller.POINTER_GAIN
        x, y = x_old + delta_x * ratio, y_old + delta_y * ratio
        return (x, y)

    @staticmethod
    def pinch_control_init(hand_result):
        # Capture reference coordinates at pinch start.
        Controller.pinchstartxcoord = hand_result.landmark[8].x
        Controller.pinchstartycoord = hand_result.landmark[8].y
        Controller.pinchlv = 0
        Controller.prevpinchlv = 0
        Controller.framecount = 0

    @staticmethod
    def pinch_control(hand_result, controlHorizontal, controlVertical):
        """Call action callback based on stable pinch direction and level."""
        # When displacement is stable for several frames, trigger action.
        if Controller.framecount == 5:
            Controller.framecount = 0
            Controller.pinchlv = Controller.prevpinchlv

            if Controller.pinchdirectionflag is True:
                controlHorizontal()
            elif Controller.pinchdirectionflag is False:
                controlVertical()

        lvx = Controller.getpinchxlv(hand_result)
        lvy = Controller.getpinchylv(hand_result)

        # Decide active axis by larger displacement magnitude.
        if abs(lvy) > abs(lvx) and abs(lvy) > Controller.pinch_threshold:
            Controller.pinchdirectionflag = False
            if abs(Controller.prevpinchlv - lvy) < Controller.pinch_threshold:
                Controller.framecount += 1
            else:
                Controller.prevpinchlv = lvy
                Controller.framecount = 0

        elif abs(lvx) > Controller.pinch_threshold:
            Controller.pinchdirectionflag = True
            if abs(Controller.prevpinchlv - lvx) < Controller.pinch_threshold:
                Controller.framecount += 1
            else:
                Controller.prevpinchlv = lvx
                Controller.framecount = 0

    @staticmethod
    def handle_controls(gesture, hand_result):
        """
        Central gesture-to-action dispatcher.

        Gesture mapping:
        - V_GEST -> move cursor (and arm click commands)
        - FIST -> click-and-drag
        - MID -> left click
        - INDEX -> right click
        - TWO_FINGER_CLOSED -> double click
        - PINCH_MINOR -> scrolling
        - PINCH_MAJOR -> brightness/volume
        """
        x, y = None, None
        if gesture != Gest.PALM:
            x, y = Controller.get_position(hand_result)

        # Reset mode flags when gesture context ends.
        if gesture != Gest.FIST and Controller.grabflag:
            Controller.grabflag = False
            pyautogui.mouseUp(button="left")

        if gesture != Gest.PINCH_MAJOR and Controller.pinchmajorflag:
            Controller.pinchmajorflag = False

        if gesture != Gest.PINCH_MINOR and Controller.pinchminorflag:
            Controller.pinchminorflag = False

        # Gesture mappings (stateful: some actions depend on prior V_GEST flag).
        if gesture == Gest.V_GEST:
            Controller.flag = True
            pyautogui.moveTo(x, y, duration=Controller.POINTER_MOVE_DURATION)

        elif gesture == Gest.FIST:
            if not Controller.grabflag:
                Controller.grabflag = True
                pyautogui.mouseDown(button="left")
            pyautogui.moveTo(x, y, duration=Controller.POINTER_MOVE_DURATION)

        elif gesture == Gest.MID and Controller.flag:
            pyautogui.click()
            Controller.flag = False

        elif gesture == Gest.INDEX and Controller.flag:
            pyautogui.click(button="right")
            Controller.flag = False

        elif gesture == Gest.TWO_FINGER_CLOSED and Controller.flag:
            pyautogui.doubleClick()
            Controller.flag = False

        elif gesture == Gest.PINCH_MINOR:
            if Controller.pinchminorflag is False:
                Controller.pinch_control_init(hand_result)
                Controller.pinchminorflag = True
            Controller.pinch_control(
                hand_result, Controller.scrollHorizontal, Controller.scrollVertical
            )

        elif gesture == Gest.PINCH_MAJOR:
            if Controller.pinchmajorflag is False:
                Controller.pinch_control_init(hand_result)
                Controller.pinchmajorflag = True
            Controller.pinch_control(
                hand_result,
                Controller.changesystembrightness,
                Controller.changesystemvolume,
            )
