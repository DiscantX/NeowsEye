# inside main.py or a new test script
from client import Client
from display import show_image
from vision import crop_region, extract_text, preprocess_for_ocr


def main():
  client = Client("Slay the Spire")
  client.prepare_window(always_on_top=True)

  # Capture the clean client interior
  frame = client.capture_view()

  if frame is not None:
    # Example: Define a bounding box for a UI region (x, y, width, height)
    # Let's say we want to test capturing the top-left gold or health area
    # (You can tweak these numbers based on visual inspection using cv2.imshow)
    sample_box = (175, 0, 55, 30)

    # 1. Crop the region
    cropped_patch = crop_region(frame, sample_box)

    # 2. Process to black-and-white / high contrast
    binary_patch = preprocess_for_ocr(cropped_patch)

    # 3. Run Tesseract
    recognized_text = extract_text(binary_patch)
    print(f"[Neow's Eye OCR Result]: '{recognized_text}'")

    # Show both the binary patch and original crop for debugging
    show_image(binary_patch)


if __name__ == "__main__":
  main()