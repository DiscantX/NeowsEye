import win32con
import win32gui

class ClientRect:
  def __init__(self, window_title="Slay the Spire"):
    self.window_title = window_title
    self.handle = self._get_window_handle(window_title)

    if self.handle:
      self._set_rect_properties()

  def _get_window_handle(self, window_title):
    handle = win32gui.FindWindow(None, window_title)
    if not handle:
      print(f"[Neow's Eye] Window not found: {window_title}")
      return None
    return handle

  def _set_rect_properties(self):
      # Get the inner client coordinates relative to the window itself
      client_rect = win32gui.GetClientRect(self.handle)
      client_left, client_top = win32gui.ClientToScreen(self.handle, (client_rect[0], client_rect[1]))
      client_right, client_bottom = win32gui.ClientToScreen(self.handle, (client_rect[2], client_rect[3]))

      # Assign absolute screen positions for the pure interior canvas
      self.left = client_left
      self.top = client_top
      self.width = client_right - client_left
      self.height = (client_bottom - client_top)  # Excludes the title bar
    
  def move_to_top_left(self):
    """Snaps the window to coordinates (0,0) only if it isn't already there."""
    if self.handle:
        # Get current outer window rectangle (left, top, right, bottom)
        window_rect = win32gui.GetWindowRect(self.handle)
        win_left, win_top, win_right, win_bottom = window_rect

        # If it's already at (0, 0), skip to prevent redundant shifting
        if win_left == 0 and win_top == 0:
          return

        # Calculate current outer dimensions
        width = win_right - win_left
        height = win_bottom - win_top

        win32gui.MoveWindow(self.handle, 0, 0, width, height, win32con.SWP_NOZORDER | win32con.SWP_NOSIZE)
        self._set_rect_properties()  # Refresh bounds post-move

  def bring_to_foreground(self):
    """Brings the window to focus on first run or activation."""
    if self.handle:
      if win32gui.IsIconic(self.handle):
        win32gui.ShowWindow(self.handle, win32con.SW_RESTORE)
      win32gui.SetForegroundWindow(self.handle)

  def set_always_on_top(self, enable=True):
      """Pins or unpins the window to stay always on top."""
      if self.handle:
        insert_after = (win32con.HWND_TOPMOST if enable else win32con.HWND_NOTOPMOST)
        win32gui.SetWindowPos(self.handle, insert_after, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)