"""
Gemini Smoke Test

The smallest possible check that we can reach the Gemini API and get a
real response back -- no game state, no gemini_client.py, no state.py.
Run this on its own before wiring anything else up.

Requires: pip install google-genai python-dotenv
Requires: a .env file (or GEMINI_API_KEY already set in the environment)
  containing: GEMINI_API_KEY=your_key_here
"""

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client()  # picks up GEMINI_API_KEY from the environment

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="You are a Slay the Spire expert. Who is Neow?",
)

print(response.text)