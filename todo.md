# TODO, BUGS, & FEATURE REQUESTS

## TODOs

### When to provide additional info to Gemini

This is a complicated question. We need to determine when to provide additional information to Gemini, and what information to provide. Some examples of when we might want to provide additional information:

* Provide gold on first prompt given at: Unkown, merchant, rest (and future map decisons)
* Provide health: Every prompt? It's almost universally required.
* Provide cards in deck: Every combat start? Every card reward choice/shop? Never, does it track it fine on its own?
* In combat, we need to reprompt when the situation changes mid-turn, such as drawing more cards.
* In combat, if we have a card that interacts with the draw or discard pile, do we provide their contents? How do we know which cards do this?
* Map screen -- a more complicated, already deferred feature. When at a crossroads, provide options, but what: next node? contents of hallways up to next crossroad? full map network? What do we provide at act start? Same questions.

### Update token usage

This is currently a deferred task. We need to calculate token usage and display it in the GUI. Currently the UI element is a dead end.

### Reorganize project structure

We currently have aa flat project structure. We should reorganize the project structure to be more modular and easier to navigate. This will make it easier to find and fix bugs, as well as to add new features.

### Remove uui from prompt

We are currently including the uui of each card in the prompt. This is not necessary, and it is taking up valuable token space. We should remove the uui from the prompt, and only include the card name and any relevant information about the card.

## Bugs

### Extra `+` on upgraded cards

Gemini is sometimes giving upgraded cards an extra `+` in the name. (ie Bash++ instead of Bash+). Are we introducing that on the code level, or is it a bug in the model's understanding of the card names?

### Variable energy cards

Cards that have variable energy, such as Whirlwind's "Deal 8 damage to all enemies x times", show an energy value of -1 in the prompt. We previously flagged this. The AI does not always know what this meaans; interstingly, it did seem to learn after we used it the first time, though this is not confirmed to be consistent behavior.

### Reset timezone

The GUI timezone reset element is not what was expected. It should be showing what time the reset happens, either in Pacific time (Gemini's timezone) or in the user's local timezone.

### Flaws in Gemini's reasoning and understanding of game mechanics

These represent a failure in the model's understanding of the game mechanics, and we need to find a way to correct it. We may need to provide more information about the game mechanics in the prompt, or we may need to adjust the model's training data (RAG learning).

#### Gemini's understanding of card ordering

Gemini sometimes suggests playing cards in an order that is not optimal or even possible. For example, it may suggest playing a card that removes the rest of the hand from play, and then to play a card that is in the hand that was just removed. *Second Wind* is one such card. The card's effect is: `Exaust all non-combat crds in your hand. Gain block for each card exausted.`

Gemini may suggest a sequence such as:

    Play Second Wind (1 energy), exhausting the Burn and the Strike to generate 29 total block, which comfortably negates the incoming multi-hit damage. Then, play the Defend (1 energy) to provide a safety buffer and use your final energy to play the remaining Strike. This sequence keeps you healthy while thinning your deck of the status card.

Note that not only is the order of cards incorrect, but the model also does not understand that Strike is a combat card and will not be exausted by Second Wind; instead it is the Defend card that will be exausted, which it then suggests to play. This is a knowledge bug or hallucination in and of itself.

#### Gemini's understanding of what cards effect what enemies

There have been the odd occasion where Gemini suggests that a card will affect an enemy that it will not, such as a Strike card, which only affects one enemy, being suggested to be played on multiple enemies. This is a bug in the model's understanding of the game mechanics, and we need to find a way to correct it. We may need to provide more information about the game mechanics in the prompt, or we may need to adjust the model's training data.

#### Gemini's understanding of whether cards are held to the next round

Gemini sometimes suggests that a card will be held to the next round when it will not -- with the exception of some effects that allow cards to be held, such as the "Retain" effect, cards are always disposed of at the end of the round. Example of incorrect feedback Gemini provided:

    Play Battle Trance (0 energy) to draw more cards and maximize your offensive options. Follow up with Whirlwind++ (3 energy) to deal massive AoE damage while Hexaghost is still Vulnerable. Save your other cards for the next hand, as this play maximizes your current energy efficiency and damage potential.

This is a bug in the model's understanding of the game mechanics, and we need to find a way to correct it. We may need to provide more information about the game mechanics in the prompt, or we may need to adjust the model's training data.

#### Gemini fails to predict our loss of the game

This seems to occur when we are in a state in which we are about to lose, and have no options for winning. Example:

    Play Battle Trance (0 energy) to draw into more cards, followed by Pommel Strike (1 energy), then another Pommel Strike (1 energy) to maximize damage while Hexaghost is Vulnerable. Finally, play Cleave (1 energy) to finish off the remaining health. This aggressive play order utilizes your remaining energy to secure the kill before taking further damage.

We lost this round because we were about to take more damage than we could handle, and there was no way to win. Gemini did not predict this, and instead suggested that the play order would result in our win.

## Features

### Styling

Have gemini wrap certain words with markdown or similar. Possibly make semantic such as `[relic][/relic]`. We can then style the output in the GUI. We would want this to be a setting. A few examples of what to style, not definitive:
 -- Card names
 -- Relic names
 -- Enemy names
 -- Buff/Debuff names
 -- Hp (ie. `20 hp`)
 -- Effects (different for positive and negative?)
 -- Option names to choose (like `Smith` or `Rest`, or choices such `Bannana` in the "Unknown" area)
 -- Map choices (like `Left hallway` or `Right hallway`)

### RAG learning -- Wiki + Q&A

Feed a copy of the Fandom wiki to Gemini using the API at the start of each run. We would want to pre-process the wiki to strip out for example html. We may also want a separate RAG Q&A that we hand crafted.

### Run summary & RAG learning

At the end of eaach run, have Gemini summarize the run. Treat it like a post-mortem. What went well, what went poorly, what could have been done differently. Include both strategic insights as well as blunders the AI made in its assumptions about how the game works. This could be used to improve the model's performance in future runs. We could also use this to create a RAG (Retrieval-Augmented Generation) system where we store these summaries and use them to inform future runs.

Include the option to save this to a file or database. We can have sepaarate files, such that each represents a different "AI" profile. This way we can have different AI personalities, and we can also have a "meta" AI that learns from the summaries of all the other AIs.

We may want a database of all learnings, as well as individual RAG files that are specific to each AI. Somewhere, we can use a higher-level Gemini model to analyze the summaries and create a "meta" summary that can be used to inform future runs. This could be a good use case for using our limited credits with better models.

### Periodic "state-of the game" update

At certain intervals out of combat, have Gemini provide a summary of the current state of the game. This should be a high-level summary of the current strategy and outlook. It should not include things such as entire lists of cards in the deck, but it should include things such as current health, gold, important relics and cards central to the strategy, and any other relevant information. This could be useful for the player to get a sense of how the game is going and what they should be focusing on. This is a good place to use a better model, since it is a more strategic and high-level summary. We can also use this to inform the AI's decisions in future runs.

### User feedback and questions

Include an input box in the GUI (or similar in terminal) where the user can provide feedback and ask questions. Since this is a coach, asking questions is important. Feedback provided can also be used when the AI gives its post-mortem. Also distingush between the player's input and the AI's output. We can have a "feedback" section in the GUI where the user can see the AI's responses to their questions and feedback. At minimum, use different colors for the player's input and the AI's output.

This could be useful for debugging, as I can ask Gemini what it currently knows (such as cards in the deck).
