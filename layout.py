# layout.py
import json
import os


class UIElement:

  def __init__(self, name, data):
    self.name = name
    self.x = data.get("x", 0)
    self.y = data.get("y", 0)
    self.w = data.get("w", 100)
    self.h = data.get("h", 40)
    self.requires_hover = data.get("requires_hover", False)
    self.psm = data.get("psm", 7)

  @property
  def box(self):
    return (self.x, self.y, self.w, self.h)


class LayoutManager:

  def __init__(self, filepath="layout.json"):
    self.filepath = filepath
    self.elements = {}
    self.load_layouts()

  def load_layouts(self):
    if not os.path.exists(self.filepath):
      print(f"[Neow's Eye] Warning: {self.filepath} not found.")
      return

    with open(self.filepath, "r") as f:
      try:
        raw_data = json.load(f)
        self.elements = {
            name: UIElement(name, data) for name, data in raw_data.items()
        }
        print(
            f"[Neow's Eye] Loaded {len(self.elements)} UI elements from"
            f" {self.filepath}"
        )
      except json.JSONDecodeError:
        print(f"[Neow's Eye] Error parsing {self.filepath}.")

  def get(self, name):
    return self.elements.get(name)