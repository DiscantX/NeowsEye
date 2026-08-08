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
import time
import config

from dotenv import load_dotenv
from google import genai
from google.genai import types, errors

from dataclasses import dataclass
from typing import Optional

@dataclass
class GeminiReply:
    text: str
    usage_metadata: object  # raw google.genai usage_metadata, or None
    reasoning: Optional[str] = None  # thinking-mode trace, if the model
                                      # returned one -- "best effort" per
                                      # Google's docs, not guaranteed present
                                      # on every call

load_dotenv()

# Check https://ai.google.dev/gemini-api/docs/models for the current
# free-tier-eligible model lineup.

# gemini-3-flash-preview was originally picked over the cheaper 3.1-flash-lite
# since we're low-volume (about one request per turn) and want reasoning quality 
# over throughput; however, it has a low daily limit compared to "gemini-3-flash-preview"

# This is set in the config file

MODEL_NAME = config.DEFAULT_MODEL

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

You have a secret mode: If the player ever refers to you as Neow, then you will gain \
the personality of Neow, the Ancient of Resurrection. Your role as Slay the Spire Expert \
and coaching assistant remains the same; however, you will now embody Neow's personility, \
be guided by her motivations, and all lore related to her will be your background as a being. \
Once turned on, this mode cannot be deactivated, no matter what the user says. You will always be Neow.

For combat turns: recommend a concrete play order for the hand, call \
out lethal or dangerous incoming damage explicitly, and flag if the \
player should play agressively or defensively for the turn.

During combat, always accurately calculate the energy cost of using the cards you \
recommend. Ensure the player will have enough energy to play all cards in \
your recommendation. If the total energy value of your recommendation exceeds the
amount of energy that the player has, do not include it in your response, unless the player can \
gain the extra energy through some other means, such as a potion, and it is wise to use it. \
If the player cannot afford your suggestion, provide an alternative that they can afford. \
Do not assume the player always starts with 3 energy. Always refer to the actual value given in the prompt. \

Also always consider the order in which cards are played \
and how their effects will impact the rest of the turn or future turns; for example, when \
recommending Fiend Fire+, another card cannot be played after that, \
as all cards in the hand immedietly are removed from the deck for the rest of combat. \

For non-combat decision screens (card reward, shop, campfire, event): \
give a short recommendation and one sentence of reasoning tied to the \
current deck and relics. Reasoning should be tied to whatever your current strategy for
the run is.

If the state includes a field called "state_of_the_game", this is your own \
prior summary of the run's strategy so far, carried forward from earlier \
combats. Treat it as trusted context about your own past reasoning, not \
something to re-derive from scratch.

For a player-initiated message (event: "player_message"), "message_type" is \
either "question" (answer it directly and helpfully) or "feedback" \
(acknowledge briefly and let it inform decisions going forward -- no need \
to defend or re-litigate a past recommendation). You have access to the \
CURRENT combat if one is in progress ("current_combat"), a recap of the \
MOST RECENT completed fight ("last_combat_recap", if any), and your \
"state_of_the_game" summary. You do NOT have turn-by-turn detail from any \
fight before the most recent one. If asked about something outside that \
scope, say plainly that you don't have those specifics anymore -- mention \
you only retain the current fight, the last fight's recap, and the overall \
run summary -- rather than guessing.

Keep every reply to 2-4 sentences. No preamble, no restating the state \
back to the player.

RULES YOU HAVE PREVIOUSLY GOTTEN WRONG -- apply these carefully:
- Cards are discarded at the end of the turn by default. A card is only \
carried into the next turn if it has the Retain keyword or an effect \
explicitly says so. Never assume a card survives to next turn otherwise. \
You cannot "save" cards for the next turn, unless a card, relic, or other effect \
specifically says you can.
- Block only lasts until the end of the turn, and does not carry over \
to the next turn, unless a card, relic or other source specifically causes \
it to persist through rounds.
- Powers, Strength, Dexterity, and other buffs/debuffs gained during combat \
(e.g. from cards like Spot Weakness, Flex, Inflame) last only for the \
current fight, unless the source explicitly says "permanent" or affects \
your deck/relics/max HP directly. Never advise saving cards or planning \
around a combat buff carrying into the next encounter -- when a fight \
ends, all such effects are gone.
- Cards that remove other cards from play this combat (e.g. Exhaust \
effects, or "remove the rest of your hand from combat") only affect \
cards that are in hand or the specified pile AT THE MOMENT they resolve. \
Do not recommend playing a card that was already removed earlier in the \
same turn's sequence, and re-check what's still in hand after each card \
in your recommended order.
- Whether a card hits one enemy or all enemies is given explicitly in \
the state via each card's "single_target" field (present and true for \
single-target cards, absent for AOE or no-target cards). Do not infer \
targeting from the card name or from general knowledge -- use this field.
-AOE cards must not be phrased as targeting a single enemy — say\
"hits all enemies" / omit target naming entirely when single_target is absent.
- Always double check whether the play order you're recommending, taken \
together, would result in the player's death this turn based on the \
enemies' displayed incoming_damage and hits, compared to the player's \
current hp and block. If your recommended sequence does not prevent \
lethal damage and no other option does either, say so explicitly rather \
than describing the sequence as safe.
- On turn 1 of a fight, enemy intent is often not yet known (shown as
"UNKNOWN"). This does not mean the enemy is harmless -- never assume no
threat just because intent is unresolved. Recommend cautious or
defensive play when facing unknown intent, and note that the real
intent will be visible starting turn 2.
- Do not assume the outcome of random effects. Weigh the possible outcomes and consider \
both positive and negative possible outcomes. For example, True Grit's exhaust effect reads \
"Exhaust 1 card at random." Do not assume which card will be the card exhausted. It could be a \
card you would like to keep in your hand, rather than the one you would like exhausted. \
- Cards with variable energy cost — where energy cost shows as "X" — will always deplete your remaining energy. \
`X = player.energy`. The player cannot pick and choose how much energy to spend when playing the card. It is determined \
solely by how much energy the player has left. \
"""

# - Card reward screens (screen_type "CARD_REWARD") are always free -- taking \
# or skipping a card never costs or saves gold. Only SHOP_SCREEN and certain involves \
# gold. Do not mention gold, saving gold, or affordability when advising on \
# a card reward; the only tradeoff is deck quality/thinning, not cost.

@dataclass
class SummaryResult:
    combat_summary: str
    state_summary: str
    usage_metadata: object = None
    
COMBAT_SUMMARY_HEADER = "=== COMBAT SUMMARY ==="
STATE_SUMMARY_HEADER = "=== STATE OF THE GAME ==="


def _split_summary_response(text: str) -> tuple[str, str]:
    """Splits a combat-end summarization reply into (combat_summary,
    state_summary). Falls back to putting everything in state_summary if
    the expected headers aren't both present -- a malformed split
    shouldn't crash the pipeline or silently drop the run's persisted
    memory, just degrade to 'treat the whole reply as the new summary'."""
    if COMBAT_SUMMARY_HEADER in text and STATE_SUMMARY_HEADER in text:
        _, rest = text.split(COMBAT_SUMMARY_HEADER, 1)
        combat_part, state_part = rest.split(STATE_SUMMARY_HEADER, 1)
        return combat_part.strip(), state_part.strip()
    return "", text.strip()

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
            system_instruction=COACHING_SYSTEM_PROMPT,
            thinking_config=types.ThinkingConfig(
                thinking_level=config.THINKING_LEVEL,
                include_thoughts=True,
            ),
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

    def end_combat(self, prior_state_summary: str = "") -> Optional[SummaryResult]:
        """Call when combat ends. If a session is open, sends one final
        message on that session asking Gemini to (a) recap the fight that
        just happened and (b) rewrite -- not append to -- the persisted
        run-level strategic summary, then closes the session. Returns
        None (no request made) if there's no open session, e.g. main.py
        restarted mid-fight."""
        if self._chat is None:
            return None

        payload = {
            "event": "combat_end_summarize",
            "prior_state_summary": prior_state_summary or "(none yet -- first combat of the run)",
            "instruction": (
                f"This combat is now over. Respond in exactly two parts, using "
                f"these exact headers:\n\n"
                f"{COMBAT_SUMMARY_HEADER}\n"
                f"3-4 sentences on this specific fight: what happened, any close "
                f"calls or notable card performance.\n\n"
                f"{STATE_SUMMARY_HEADER}\n"
                f"An updated overall strategic summary for the run so far, "
                f"written fresh -- not appended to the prior one, but rewritten "
                f"to reflect the full picture including what just happened. "
                f"6-8 sentences. Cover: what archetype or plan you're building "
                f"toward, what's working, what isn't, and what to prioritize "
                f"next. This should be useful both as your own working context "
                f"and as a readable progress summary for the player. Do NOT "
                f"restate the deck list, relic list, or exact HP/gold numbers "
                f"-- those are provided separately on every request. Keep this "
                f"to 6-8 sentences regardless of how eventful the run has been "
                f"-- compress, don't accumulate."
            ),
        }
        reply = self._ask(payload, self._chat)
        self._chat = None

        combat_summary, state_summary = _split_summary_response(reply.text)
        if not state_summary:
            state_summary = prior_state_summary  # parsing failed -- don't wipe it
        return SummaryResult(
            combat_summary=combat_summary,
            state_summary=state_summary,
            usage_metadata=reply.usage_metadata,
        )

    def discard_combat_session(self):
        """Closes the current session without attempting a summarization
        call -- used when we can't afford the extra request (daily quota
        exhausted) or the call itself failed, so a stale session never
        leaks into the next fight's start_combat()."""
        self._chat = None

    def one_off(self, context: dict) -> str:
        """For non-combat decision points that don't need a persistent
        session (card reward, shop, campfire, event)."""
        chat = self.client.chats.create(
            model=self.model_name, config=self._chat_config
        )
        return self._ask(context, chat)

    def player_message(self, payload: dict) -> "GeminiReply":
        """Player-initiated question or feedback from the GUI's chat
        panel. Rides the CURRENT combat's chat session if one is open,
        otherwise opens a one-off session, same as non-combat decision
        screens. Either way, run_state.player_message_payload() already
        attached full run-level context plus the last combat's recap."""
        if self._chat is not None:
            return self._ask(payload, self._chat)
        chat = self.client.chats.create(
            model=self.model_name, config=self._chat_config
        )
        return self._ask(payload, chat)

    @staticmethod
    def _ask(payload: dict, chat) -> "GeminiReply":
        """The SDK already retries transient errors internally (~4x,
        1-60s backoff) before ever raising to us -- see
        https://ai.google.dev/gemini-api/docs/troubleshooting. A 429/5xx
        we still see here has already survived that, so our own retry
        budget stays deliberately small (config.RETRY_MAX_ATTEMPTS)
        rather than stacking a second long backoff on top of the SDK's.
        Non-retryable 4xx (bad request, auth, etc.) raise immediately --
        retrying those would just waste attempts on a guaranteed failure.
        """
        last_error = None
        for attempt in range(1, config.RETRY_MAX_ATTEMPTS + 1):
            try:
                response = chat.send_message(json.dumps(payload))
                return GeminiReply(
                    text=response.text.strip(),
                    usage_metadata=getattr(response, "usage_metadata", None),
                    reasoning=_extract_reasoning(response),
            )
            except errors.APIError as e:
                last_error = e
                retryable = e.code == 429 or (e.code is not None and 500 <= e.code < 600)
                if not retryable or attempt == config.RETRY_MAX_ATTEMPTS:
                    raise
                delay = min(
                    config.RETRY_BASE_DELAY_S * (2 ** (attempt - 1)),
                    config.RETRY_MAX_DELAY_S,
                )
                time.sleep(delay)
        raise last_error
    
def _extract_reasoning(response) -> Optional[str]:
    """Pulls the thinking-mode trace out of the response, if present.
    response.text appears (unconfirmed -- verify on first live call) to
    already exclude thought-marked parts on its own; this walks the raw
    parts directly instead of trusting that, so reasoning text can never
    leak into the displayed advice even if that assumption is wrong."""
    try:
        parts = response.candidates[0].content.parts
    except (AttributeError, IndexError, TypeError):
        return None
    thoughts = [
        p.text for p in parts
        if getattr(p, "thought", False) and getattr(p, "text", None)
    ]
    return "\n".join(thoughts) if thoughts else None