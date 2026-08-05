import cv2
import mss
import numpy as np
from window_manager import ClientRect

def client_interior(window_title="Slay the Spire"):
  # Initialize our ClientRect wrapper object
  rect = ClientRect(window_title)

  if not rect.handle or not is_window_valid(rect):
    return None

  # Define the bounding box for mss matching object properties
  monitor = {
      "left": rect.left,
      "top": rect.top,
      "width": rect.width,
      "height": rect.height,
  }

  # Capture window interior via mss
  with mss.mss() as sct:
    sct_img = sct.grab(monitor)
    frame = np.array(sct_img)
    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

  return frame

def is_window_valid(rect):
  if rect.width <= 0 or rect.height <= 0:
    print("[Neow's Eye] Window is minimized or invalid dimensions.")
    return False
  return True