<!-- version: 1 · tier: compact · pattern: none:extraction (background quality pass on prefetched flashcards) · output: {"unsupported": [int]} -->

## system

Compare numbered flashcards with the revision notes they were made from. List the numbers of
the cards whose answer the notes do not support or contradict. A card that only says the same
thing in other words is supported. The cards are in {language_name}.
Reply with JSON only: {{"unsupported": [2, 7]}} (an empty list when every card is supported).

## user

NOTES
{notes}

CARDS
{cards}
