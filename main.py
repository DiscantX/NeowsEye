from display import show_image
from client import Client

def main():
  print("[Neow's Eye] Starting coaching session...")

  # Instantiate the high-level client wrapper
  client = Client("Slay the Spire")

  # Setup layout and position
  client.prepare_window()

  # Capture and display the interior feed
  frame = client.capture_view()
  show_image(frame)

if __name__ == "__main__":
  main()