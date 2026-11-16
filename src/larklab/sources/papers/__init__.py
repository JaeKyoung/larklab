"""One module per paper source; `metadata_lookup` merges them."""

# How far back a crawler catches up after missed days. Longer outages lose the
# oldest papers rather than flooding Slack with a month of recommendations.
MAX_CATCH_UP_DAYS = 7
