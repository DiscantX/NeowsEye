from capture import client_interior
from window_manager import ClientRect

class Client:
  def __init__(self, window_title="Slay the Spire"):
    self.window_title = window_title
    self.rect = ClientRect(self.window_title)

  def prepare_window(self, always_on_top=True):
    """Orchestrates window placement and focus behavior on startup."""
    if self.rect.handle:
      self.rect.move_to_top_left()
      self.rect.bring_to_foreground()
      if always_on_top:
        self.rect.set_always_on_top(always_on_top)

  def capture_view(self):
    return client_interior(self.window_title)