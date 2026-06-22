"""External-service clients used by skills (Jira sprint data, Spin publishing).

Thin, dependency-light wrappers — pure normalization is kept separate from I/O so it
can be unit-tested without the network (the pattern used across the codebase)."""
