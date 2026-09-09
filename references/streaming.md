# Streaming guidance

Availability is a live, region-specific fact. Before saying a film is on Netflix, Max/HBO, Prime Video, or another service, verify it for the user's country at recommendation time. Include a date such as “checked today for the US.”

Do not cache availability for more than 24 hours. If current verification is unavailable, say “availability unverified” rather than inferring it from an old result. A licensed provider-data API is appropriate only when the user supplies and authorizes its credentials; otherwise use an allowed current web lookup for finalists only.
