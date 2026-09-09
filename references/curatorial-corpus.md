# Curatorial corpus

This layer supplies film-studies context that TMDB does not: movements, national cinemas, teaching sequences, aesthetic motifs, and cited authority. It stores factual film-to-list membership and short original notes, never copied critical prose.

## Source hierarchy

| Tier | Source type | Role in recommendations |
|---|---|---|
| 1 | Named university syllabus or course screening list | A pedagogical sequence from an identifiable instructor or department. |
| 2 | Film institute or archive programme | A curator's movement primer and canon, with historical context. |
| 3 | Publisher / repertory collection | A strong, narrower auteur, national-cinema, or motif path. |
| 4 | Knowledge graph | Candidate expansion only; never sufficient evidence for a movement label. |

Each imported list requires its source URL, source title, source type, movement or study path, optional curator/institution, retrieval date, and the listed films. A film can belong to competing interpretations; memberships are evidence, not a final taxonomy.

## Recommendation method

1. Choose a path from the user's demonstrated affinities or stated curiosity.
2. Retrieve candidates from Tier 1–3 lists, then expand through director, country, period, and explicitly documented influence links.
3. Exclude watched titles and rank using the user's positive and negative profile, trusted-friend support, and source strength.
4. Return a small syllabus-style sequence: entry point, deepen, boundary-pusher, and bridge to a neighboring movement. Cite every path source.

Do not equate popularity, a generic genre, or a single vector-nearest result with curatorial value.

## Initial source registry

See `curriculum/source_registry.json`. Add sources conservatively. Prefer a small, accountable corpus over bulk scraping unattributed listicles.
