# Unseen-First Search, Source Deduplication, and Agent Feedback — Design

**Date:** 2026-10-26
**Target:** `mohd012z/kutepboku`, based on PR #12 (`feat/ai-assistant`, head `bb3a761430588b1268791c40d2b5df04210f0340`)
**Status:** Proposed; implementation requires owner approval.

## Intent

Repeated searches should prioritize relevant results the requesting user has not actually seen before. Earlier result sets must remain accessible. The bot must avoid duplicate books, repositories, and redundant source API requests while retaining source diversity and trustworthy licensing checks. An agent should learn useful search-performance signals, not merely accumulate XP.

## Current evidence

- `verified_search()` retrieves candidates from Internet Archive advanced search, Project Gutenberg and Open Library, merges by exact `source_url`, then performs one LLM relevance screening. Distinct URLs can represent the same work; Open Library may re-fetch Internet Archive metadata already fetched by the IA path.
- `/find` runs `verified_search()` and GitHub repository discovery. `apps_for()` deduplicates only exact `full_name` case-sensitively after merging curated and live results.
- The router persists only the active FSM state and a result page. It does not track which items were displayed across searches, so repeated normalized queries can display the same first-page items.
- `agent_skills.py` stores search counts, topics, XP and levels; it does not use this history to select sources or rank candidates.

## Goals

1. No duplicate logical work within one eBook result set, despite alternative download URLs, with conservative identity resolution.
2. No duplicate canonical GitHub repository within a result set, regardless of case, URL shape, or curated/live overlap.
3. One source search per source + normalized query + search parameters per operation; concurrent identical requests share one in-flight operation. IA metadata for the same identifier is fetched at most once within that operation.
4. Repeat searches show unseen *relevant and licensed* results first, per user and across entry commands. A shortfall must be explained, not filled with irrelevant or forbidden content.
5. Only records actually displayed to the user count as seen: opening the first page marks its items; moving pages marks the newly displayed page. Fetching a candidate pool does not mark its undisplayed items. Seen identity is **per user across all topics and commands**; query-specific history is stored separately.
6. A `Previous results` action lets users revisit exact historical result sets and pages; viewing history does not consume new results.
7. Search categories keep meaningful command-specific outputs: ebook search, Find ALL (books + apps), MQL5 source, automation tools, and prompt generation remain distinct.
8. All existing rights checks, user allowlists, callback ownership checks, file-type and size limits, and fallback behavior remain intact.

## Non-goals

- No new model training, weight updates, or claim of autonomous reasoning improvement.
- No crawling private Telegram content, circumvention of service restrictions, or unlicensed document distribution.
- No guarantee that two searches over an exhausted or tiny corpus can always return different relevant results.
- No replacement of the existing Telegram framework or broad rewrite of domain-specific menus.

## Considered approaches

1. **URL-only dedup and shuffle**: small change but fails on multiple URLs for one work, repeats source calls, and randomizes quality. Rejected.
2. **Cross-source coordinator + persistent seen history (selected)**: adds small focused modules and SQLite tables; preserves stable relevance and allows accurate, per-user rotation. More code and migration tests, but satisfies source and result requirements.
3. **External search cluster/vector DB**: powerful at scale but adds deployment, credentials and operations cost that this bot does not yet need. Deferred.

## Proposed components and contracts

### 1. Source and identity normalization

New `search_identity.py`:

- `normalize_query(text: str) -> str`: Unicode NFKC, case-fold, collapse whitespace, trim harmless search filler; preserve meaningful digits and symbols. Enforce the existing 200-character bound. Do not conflate unrelated queries.
- `book_identity(item: dict) -> str`: prefer explicit stable work identifiers (IA item ID, Open Library work key, Gutenberg numeric ID), then verified normalized `title + author` when both are present; otherwise normalize the exact URL, stripping tracking parameters only. Merge only when identity evidence is strong; preserve distinct editions when identity is uncertain.
- `repo_identity(item: dict) -> str`: lowercase canonical `owner/repo` after strict parsing.
- `dedupe_candidates(items, identity_fn)`: stable first-valid-wins with optional provenance aliases attached. Do not discard a better licensed format solely because it was encountered second; prefer verified downloadable PDF/EPUB, usable metadata and direct source link.
- Explicit source provenance and `work_id`/ `repo_id` fields accompany results without breaking existing `id` callback values.

### 2. Source request coordinator

New `search_coordinator.py`, called by the existing `search_provider.verified_search` and Find ALL app retrieval:

- A request context memoizes calls by `(source, normalized_query, stable_parameters)` and IA metadata by identifier, with thread-safe single-flight execution. An empty successful response can be cached; exceptions must not poison the cache or turn licensing failure into success.
- Persistent, bounded SQLite source cache contains only public discovery metadata (no credentials, chat IDs, private messages, or raw user queries). Cache keys use a one-way SHA-256 hash of normalized query + source + parameters; raw free-text queries are never part of shared cache keys or logs. Default positive TTL **30 minutes**, empty-success TTL **10 minutes**, IA licensing metadata TTL **30 minutes**; maximum cache entries **2,000** with oldest-expiry eviction. These are tunable configuration defaults.
- Explicit `Refresh sources` invalidates the query's expired/stale candidate cache and queries each source at most once again; refresh is user-triggered, never a silent immediate retry loop.
- Source calls remain isolated: one unavailable provider does not suppress eligible results from others. License gates are applied on every candidate before display/delivery; cached rights evidence expires and is revalidated.
- Do not merge a provider's error into an empty successful response; preserve source-error status in diagnostic metrics.

### 3. Per-user seen history and rotation

Extend `session_manager.py` with independent, additive tables (`user_sessions` remains compatible):

- `search_seen(user_id, item_type, item_key, first_shown_at, last_shown_at, last_query_hash)`, **unique by user/type/key globally across commands and queries**; retain 90 days. The query hash is optional diagnostic metadata, not part of seen-item identity.
- `search_history(user_id, history_id, query_key, search_route, result_snapshot_json, created_at)`; retain last 20 batches or 30 days per user.
- `mark_displayed(user_id, query_key, results)` atomically inserts only the current visible page, never every fetched candidate. Ensure repeated callbacks are idempotent.
- `recently_seen(user_id, item_type)` (global item ledger) and `list_history(user_id, ...)` (query-specific batches) are strictly scoped to that user. Never allow one user's callback token or history ID to access another user's batches.
- New search ranking: licensed and relevant candidates first; within equivalent relevance, unseen before previously seen; a small source-diversity tie-breaker prevents a first page dominated by one provider where other valid sources exist.
- If fewer than three unseen eligible items remain, show only the new items and a clear `No more new verified results` note; offer `Previous results`, optional `Refresh sources`, and a user-only `Clear search history` action. Never silently recycle old items as if new. Clearing history deletes that user's seen and batch rows without touching shared public source cache.
- Historical batch replay restores the exact previous order without incrementing XP or seen counts.

### 4. Router and command integration

- In `bot_router.py`, use one common search presentation service for typed queries, categories, `/android`, and Find ALL's ebook portion. Do not invoke `verified_search` twice when the same normalized query is used in one action.
- Keep the existing `sr:` pagination and selection callbacks functional; add short, ownership-checked callback tokens for `Previous results` and `Refresh sources` with Telegram's 64-byte limit.
- `/find` still offers combined ebooks and apps, not the same eBook-only output as regular search. `/mql5` and automation menus retain their dedicated source adapters.
- Preserve the existing `CHOOSE_DELIVERY` flow and file/link actions on both current and restored historical result sets.
- Clarify UI copy: `Showing N new verified results`, `Previously shown`, and source attribution. Avoid claiming all sources were searched successfully when one failed.

### 5. Agent search feedback

- Extend `agent_skills.py` with aggregated, non-sensitive counters: per-source successes, failures, eligible candidates, duplicates removed, shown items and user selections. Keep the existing XP display as a progress indicator only.
- Source health/quality metrics can adjust ranking slightly *after* rights checks and relevance, never overriding those gates. Expose a transparent `Search quality` summary rather than claiming self-training.
- No raw API keys, URLs containing tokens, private chat content, phone numbers or per-user identities in aggregate logs.

## Behavior examples

- Query `machine learning`: show page 1 with three eligible works, record only those three as seen. Search `find me machine learning ebooks` again: equivalent normalized query yields the next unseen eligible works; cached source results prevent repeated identical API calls within TTL.
- An Internet Archive candidate and Open Library candidate point to the same IA identifier: show one work, preserve both provenance entries, fetch that IA metadata once per operation.
- `/find` for `automation` shows separate eBooks and repositories; repositories are unique even if the curated and GitHub API lists differ only in capitalization.
- If no unseen licensed results remain, say so and show a history/revisit action. A source outage must not trigger repeat calls or produce invented fallback matches.

## Safety and operational constraints

- Python 3.11; preserve the repository's existing dependency policy unless an added dependency has a compelling reason.
- Persistent SQLite must be backed up on the *actual live host*, with additive schema migrations, read-only integrity checks, WAL-aware backup, and no automatic destructive restore.
- Roll out behind `SEARCH_V2_ENABLED` (default off) until live staging confirms the callback and delivery paths. Historical behavior remains available for rollback.
- Avoid in-memory-only per-user history: restart and multiple-worker behavior must be defined. Use atomic transactions and unique constraints to avoid racing seen writes.
- Source cache sharing across users is safe only for public discovery data; seen/history are per-user. Keep logs free of personal identifiers.

## Verification and acceptance criteria

Offline unit/integration tests must cover:
1. Same IA work from IA and OL, alternative encoded URLs, exact duplicate URLs; one result and one metadata lookup.
2. Distinct editions/unknown authors remain separate when there is no strong identity evidence.
3. Case-varied GitHub repo names from curated/live lists collapse to one entry.
4. First-page and later-page seen accounting; repeated identical query rotates unseen; already-exhausted query never masquerades old as new.
5. History returns exact prior order and respects user ownership, stale token, restart, retention, and the per-user clear-history action.
6. Two simultaneous identical source searches single-flight; TTL hit, expiry, refresh and provider failure.
7. /find distinct combined output; /mql5 and automation routes unaffected; LLM unavailable retains relevant rights-checked results.
8. Old session DB upgrades without losing sessions; invalid/corrupt DB handling remains safe; backup/restore regression remains green.

Run `python -m compileall -q .`, `python -m unittest discover -s tests -v`, and coverage on the entire branch. Tests must demonstrate red → green against new behavior, plus no regressions. Live Telegram integration requires a staging bot and an explicitly authorized recipient; no live messages or deployment are part of design approval.

## Open implementation decisions (builder-owned)

- Whether to introduce the coordinator as a new module or split cache/identity/history into multiple small modules for testability.
- Exact LRU/expiry eviction SQL and transaction boundaries, provided bounds and privacy invariants above hold.
- Source-diversity tie-break weighting, as long as relevance and rights verification dominate it.
- Accessibility copy of history/refresh buttons within Telegram callback size limits.
