from gesture_control.runtime import GestureController


def main():
    # Thin entrypoint: all technical pipeline logic is inside runtime.py.
    controller = GestureController()
    controller.start()


if __name__ == "__main__":
    main()
