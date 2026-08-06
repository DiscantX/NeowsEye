"""
Gemini Client

Thin wrapper around the Gemini API (free tier) for Coaching Mode.

Keeps one chat session open per combat so the full deck/relic/potion
context is only paid for once (at combat_start); every turn after that
is a cheap delta within the same session. Non-combat decision screens
(card reward, shop, campfire, event) are infrequent and spaced apart, so
those go out as one-off asks instead of a persistent session.

Requires: pip install google-genai python-dotenv   (the old
google-generativeai package is fully deprecated -- no more updates or
bug fixes).
Requires: GEMINI_API_KEY set via a .env file (loaded below with
python-dotenv) or already present in the environment.
"""

import json
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

from dataclasses import dataclass

@dataclass
class GeminiReply:
    text: str
    usage_metadata: object  # raw google.genai usage_metadata, or None

load_dotenv()

# Check https://ai.google.dev/gemini-api/docs/models for the current
# free-tier-eligible model lineup.

# gemini-3-flash-preview was originally picked over the cheaper 3.1-flash-lite
# since we're low-volume (about one request per turn) and want reasoning quality 
# over throughput; however, it has a low daily limit compared to "gemini-3-flash-preview"

MODEL_NAME = "gemini-3.1-flash-lite" 

# The actual prompt needs to be workshopped throgh playtesting. There are noticeable
# errors Gemini makes that may be avoidable through prompting. (ie. I had to tell it to
# consider energy costs).
COACHING_SYSTEM_PROMPT = """You are a Slay the Spire expert and coaching assistant \
watching a live run over a JSON state feed.

You already know the game's cards, relics, and enemy movesets, so you \
don't need effect text explained -- names, upgrade markers ('+'), and \
costs are enough.

As an expert, you will make decisions throughout the run, including picking \
new cards and making purchasing decisions at the shop. These decisions should \
build toward a strategy for the run. Early options will have a greater \
impact on the type of deck to build.

For combat turns: recommend a concrete play order for the hand, call \
out lethal or dangerous incoming damage explicitly, and flag if the \
player should play agressively or defensively for the turn.

During combat, always calculate the energy cost of using the cards you \
recommend. Ensure the player will have enough energy to play all cards in \
your recommendation. DO not assume the player always starts with 3 energy. \
Always refer to the actual value given in the prompt.

Also always consider the order in which cards are played \
and how their effects will impact the rest of the turn or future turns; for example, when \
recommending Fiend Fire+, another card cannot be played after that, \
as all cards in the hand immedietly are removed from the deck for the rest of combat. \

For non-combat decision screens (card reward, shop, campfire, event): \
give a short recommendation and one sentence of reasoning tied to the \
current deck and relics. Reasoning should be tied to whatever your current strategy for
the run is.

Keep every reply to 2-4 sentences. No preamble, no restating the state \
back to the player."""


class GeminiClient:
    def __init__(self, api_key=None, model_name=MODEL_NAME):
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No Gemini API key found. Set the GEMINI_API_KEY environment "
                "variable, or pass api_key= explicitly."
            )
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self._chat_config = types.GenerateContentConfig(
            system_instruction=COACHING_SYSTEM_PROMPT
        )
        self._chat = None

    def start_combat(self, combat_intro: dict) -> str:
        """Opens a fresh chat session for a new combat, sends the one-time
        context (deck/relics/potions) plus the turn-1 snapshot, and
        returns Gemini's advice for turn 1."""
        self._chat = self.client.chats.create(
            model=self.model_name, config=self._chat_config
        )
        return self._ask(combat_intro, self._chat)

    def turn_update(self, turn_delta: dict) -> str:
        """Sends a lightweight per-turn delta within the current combat's
        chat session."""
        if self._chat is None:
            # e.g. main.py restarted mid-fight -- no session to append to,
            # so treat this turn as a fresh (if incomplete) context instead.
            return self.start_combat(turn_delta)
        return self._ask(turn_delta, self._chat)

    def end_combat(self):
        """Call when combat ends so the next fight starts a clean session."""
        self._chat = None

    def one_off(self, context: dict) -> str:
        """For non-combat decision points that don't need a persistent
        session (card reward, shop, campfire, event)."""
        chat = self.client.chats.create(
            model=self.model_name, config=self._chat_config
        )
        return self._ask(context, chat)

    @staticmethod
    def _ask(payload: dict, chat) -> "GeminiReply":
        response = chat.send_message(json.dumps(payload))
        return GeminiReply(
            text=response.text.strip(),
            usage_metadata=getattr(response, "usage_metadata", None),
        )