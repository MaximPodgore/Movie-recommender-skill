# Ranking and explanations

Candidates are all un-watched films that appear in the user's watchlist, a trusted friend's 3.5+ rating, or a trusted friend's watchlist.

The score is deliberately simple and inspectable:

- 3 points for the user's own watchlist.
- 0.75–2 points for each friend's 3.5+ rating, multiplied by that friend's chosen weight.
- 0.75 points for each friend's watchlist, multiplied by their weight.
- 1.25 points for agreement from two or more trusted friends.
- User feedback: +1.5 for a prior “liked” signal and −3 for a prior “not interested” signal.

The script emits reasons with each score. The assistant should treat the score as a starting order, then apply stated constraints (mood, runtime, country, streaming services) and diversify the final list. Do not claim that numeric scores predict enjoyment.
