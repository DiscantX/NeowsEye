import cv2
import pytesseract

def crop_region(frame, box):
  """Crops a specific sub-rectangle from the game frame.

  box format: (x, y, width, height)
  """
  x, y, w, h = box
  return frame[y : y + h, x : x + w]


def preprocess_for_ocr(crop):
  """Converts a cropped image to high-contrast black-and-white (binary)

  optimized for Tesseract OCR.
  """
  if crop is None or crop.size == 0:
    return None

  # 1. Convert to grayscale
  gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

  # 2. Scale up (resize) the crop - Tesseract struggles with tiny text.
  # Doubling or tripling the resolution dramatically improves accuracy.
  scaled = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

  # 3. Apply Otsu's thresholding to force a pure black-and-white output
  # This strips out background noise, shadows, and gradients.
  _, thresh = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

  return thresh


def extract_text(processed_image, config="--psm 7"):
  """Runs Tesseract OCR on a preprocessed image patch."""
  if processed_image is None:
    return ""

  # psm 7 treats the image as a single text line (ideal for numbers like HP/Energy)
  text = pytesseract.image_to_string(processed_image, config=config)
  return text.strip()