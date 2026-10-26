# Search Engine V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Give every authorized user unseen-first, rights-verified, non-duplicated search results across msasoup commands, while reusing source calls and retaining exact historical result sets.

**Architecture:** Introduce small identity, source-coordination and ranking modules alongside the existing provider/router. Store public source cache and per-user seen/history in additive SQLite tables. Route ebook, Find ALL, repository and MQL5 lookups through their respective adapters without changing the existing Telegram delivery protocol.

**Tech Stack:** Python 3.11, stdlib \`sqlite3\`/\`threading\`/\`hashlib\`/\`unicodedata\`, \`requests\`, \`python-telegram-bot\` 21–22, \`unittest\`, \`coverage\`.

**Spec:** [Unseen-First Search, Source Deduplication, and Agent Feedback](../specs/2026-10-26-unseen-search-and-source-dedup-design.md)

## Global Constraints

- Base all implementation on PR #12's enhanced bot revision (\`bb3a761430588b1268791c40d2b5df04210f0340\`), not the older \`main\` router. Keep work on an isolated feature branch; do not deploy or merge automatically.
- Preserve \`agent.licensed\`, archive rights checks, authorizations, Telegram identity verification, file-signature/size checks and private admin commands.
- No new dependencies without an explicit necessity. No raw sensitive user queries, chat IDs or tokens in shared public cache or logs.
- Results count as *seen only when displayed*. The seen ledger is per-user and global across topics/commands; source responses are reusable across users only when public.
- Source calls are single-flight per source/normalized-query/parameters and IA metadata per IA identifier. Default TTLs: positive 30m, successful empty 10m, rights metadata 30m; maximum 2,000 cache entries.
- History: 20 batches / 30 days per user; seen ledger: 90 days. History replay never earns XP or marks fresh results.
- Existing callback formats stay valid; new callback payloads fit Telegram's 64-byte limit. User-bound tokens and ownership checks remain mandatory.
- \`SEARCH_V2_ENABLED\` defaults to off until staging validation. Source failure is not a successful empty result; rights and relevance outrank novelty.
- Run the entire offline suite after each behavioral task. The final gate includes compile, unit tests, coverage, search-route smoke cases and CI.

## Review Focus

The following five high-risk input classes each have a named test in the owning task:

1. Unicode and prefix collisions (e.g. \`finding aid\` vs \`find a book about AI\`) must not collapse different topics — Task 1's \`test_normalize_respects_word_boundaries\`.
2. Two distinct editions with missing author metadata must not be silently merged — Task 1's \`test_unknown_author_editions_remain_distinct\`.
3. A failed provider request may be retried later, but never cached as a successful empty hit or called twice in one operation — Task 2's \`test_failure_is_not_negative_cached\`.
4. Concurrent pagination/history callbacks cannot cross user boundaries or mark non-visible items — Task 6's \`test_history_ownership_and_page_visibility\`.
5. Exhausted results must not silently recycle old items or fail when LLM is offline — Task 7's \`test_exhausted_pool_and_llm_outage\`.

---

### Task 1: Normalize queries and canonical result identities

**Files:**
- Create: \`search_identity.py\`
- Create: \`tests/test_search_identity.py\`
- Read and preserve call contracts in: \`search_provider.py\`, \`web_sources.py\`, \`find_all.py\`

**Interfaces:**
- Produces \`normalize_query(text: str) -> str\`, \`book_identity(book: dict) -> str\`, \`repo_identity(repo: dict) -> str\`, \`dedupe_candidates(items: list[dict], identity_fn: Callable) -> list[dict]\`.
- \`dedupe_candidates\` preserves usable existing \`id\` and \`source_url\`, selects verified downloadable formats over weaker duplicates, and retains provenance aliases.

- [ ] **Step 1: Write failing tests** for equivalent filler phrasing, Unicode normalization, word-boundary preservation, same IA identifier through IA/OL URL variants, cross-source same title + known author, different editions with unknown author, malformed URL fallback, and GitHub \`Owner/Repo\` case variation.
- [ ] **Step 2: Verify RED** with \`python -m unittest tests.test_search_identity -v\`. Expected: missing functions/behavior failures matching the new tests.
- [ ] **Step 3: Implement** the four interfaces with conservative identity precedence (stable source/work ID → exact normalized title+known author → canonical URL). Never fuzzy-collapse title-only records.
- [ ] **Step 4: Verify GREEN** with the targeted test, then \`python -m unittest discover -s tests -v\`. Record counts and any unrelated failure.
- [ ] **Step 5: Commit** \`search_identity.py\` and \`tests/test_search_identity.py\` as \`feat(search): canonicalize query and result identities\`.

### Task 2: Source-request single-flight and bounded cache

**Files:**
- Create: \`search_coordinator.py\`
- Create: \`tests/test_search_coordinator.py\`
- Extend: \`session_manager.py\` (additive \`source_cache\` storage, no destructive rewrite)
- Extend: \`tests/test_session_manager.py\` (create if absent)

**Interfaces:**
- \`SourceCoordinator(store, clock=time.time)\`.
- \`run_once(source: str, normalized_query: str, parameters: dict, fetch: Callable, ttl_seconds: int = 1800, empty_ttl_seconds: int = 600) -> object\`.
- \`metadata_once(identifier: str, fetch: Callable) -> dict\` shares IA metadata per operation.
- \`refresh(source, normalized_query, parameters)\` invalidates only matching public cache entries.
- Shared cache keys are SHA-256 hashes of source/query/serialized stable parameters; cache values are public JSON metadata, with expiry and 2,000-entry bound.

- [ ] **Step 1: Write failing tests** proving one HTTP-call equivalent under two concurrent threads, cache hit across new coordinator objects, TTL expiry, empty-success 10m TTL, separate parameter keys, \`test_failure_is_not_negative_cached\`, malformed cached payload rejection, IA metadata memoization, bounded eviction, and no raw query string persisted as a cache key.
- [ ] **Step 2: Verify RED** with \`python -m unittest tests.test_search_coordinator tests.test_session_manager -v\`.
- [ ] **Step 3: Implement** the thread-safe keyed in-flight map plus additive SQLite cache schema and transaction-safe read/write/eviction. Do not hold database locks during network calls. Preserve provider error status for diagnostics.
- [ ] **Step 4: Verify GREEN**, then full suite. Inspect SQLite schema migration from a fixture containing only \`user_sessions\`.
- [ ] **Step 5: Commit** coordinator, cache storage and tests as \`feat(search): cache and single-flight public sources\`.

### Task 3: One shared eBook discovery operation

**Files:**
- Modify: \`search_provider.py\`
- Modify: \`web_sources.py\`
- Modify: \`ebook_search_pipeline.py\`
- Modify: \`tests/test_search_provider.py\`, \`tests/test_web_sources.py\`, \`tests/test_ebook_search_pipeline.py\`

**Interfaces:**
- Preserve \`async verified_search(query)\` for legacy callers.
- Add optional injectable \`coordinator\` and client/context arguments without breaking existing fixtures.
- Source keys: \`ia_advanced\`, \`gutenberg_opds\`, \`openlibrary_search\`, \`ia_metadata:<identifier>\`. One aggregated relevance-screening call remains after rights gating and canonical dedup.

- [ ] **Step 1: Write failing tests** for duplicate IA record from direct IA and OL metadata, one metadata fetch per IA identifier, distinct OPDS records, source timeout isolation, identical query requested twice from ebook and Find ALL adapters, and LLM-offline fallback with existing licensing checks enforced.
- [ ] **Step 2: Verify RED** with the three targeted modules. The duplicate/call-count cases must fail before the production change.
- [ ] **Step 3: Implement** coordinator injection, shared metadata resolver and \`dedupe_candidates(book_identity)\` before relevance ranking; preserve all existing source URL validation and license policies.
- [ ] **Step 4: Verify GREEN** and run the entire test suite.
- [ ] **Step 5: Commit** as \`feat(search): unify and deduplicate ebook sources\`.

### Task 4: Deduplicate and cache repository/tool sources

**Files:**
- Modify: \`find_all.py\`, \`auto_scout.py\`, \`mql5_scout.py\`
- Modify: \`tests/test_find_all.py\`, \`tests/test_auto_scout.py\`, \`tests/test_mql5_scout.py\`

**Interfaces:**
- \`apps_for(key, query, *, client=requests, coordinator=None)\` and \`search_repos(..., coordinator=None)\` retain existing return shapes.
- Stable source keys for GitHub search, GitHub trending and each MQL5 listing category; no duplicate identical request within one operation.
- Canonical \`repo_identity\` for curated/live merges; MQL5 code item identity is its numeric code ID.

- [ ] **Step 1: Write failing tests** for case-varied curated/live GitHub results, exact repeat source call, parameter-dependent cache segregation, MQL5 pagination identity, 20MB link fallback and one unavailable source not dropping curated entries.
- [ ] **Step 2: Verify RED** with the targeted tests.
- [ ] **Step 3: Implement** adapter reuse and stable dedup without changing download/attachment validation.
- [ ] **Step 4: Verify GREEN** and full suite.
- [ ] **Step 5: Commit** as \`feat(search): deduplicate cached repo and MQL5 lookups\`.

### Task 5: Persistent global seen ledger and exact history

**Files:**
- Modify: \`session_manager.py\`
- Modify/Create: \`tests/test_session_manager.py\`

**Interfaces:**
- \`mark_displayed(user_id: int, item_type: str, items: list[dict], query_hash: str | None = None) -> None\` idempotently writes global seen keys.
- \`recently_seen(user_id: int, item_type: str) -> set[str]\`.
- \`save_search_batch(user_id: int, batch_id: str, query: str, route: str, results: list[dict]) -> None\`.
- \`get_search_batch(user_id: int, batch_id: str) -> dict | None\`, \`list_search_batches(user_id: int, limit: int = 20) -> list[dict]\`, \`clear_search_history(user_id: int) -> None\`.
- Add unique \`search_seen(user_id,item_type,item_key)\` and owner-bound \`search_history(user_id,history_id)\`, with exact source/result snapshot.

- [ ] **Step 1: Write failing tests** for one user's same work appearing under different queries, two users with independent history, idempotent marking, untouched undisplayed candidates, malformed snapshots, 20-batch/30-day and 90-day expiry, clean history deletion, and migration of an old SQLite DB.
- [ ] **Step 2: Verify RED** with \`python -m unittest tests.test_session_manager -v\`.
- [ ] **Step 3: Implement** additive migration + atomic upserts, per-user queries and transaction-safe retention. No concurrent update may erase an unrelated user's rows.
- [ ] **Step 4: Verify GREEN** and full suite, plus existing backup/restore tests.
- [ ] **Step 5: Commit** as \`feat(search): persist per-user seen results and history\`.

### Task 6: Unseen-first ranking and result batches

**Files:**
- Create: \`search_service.py\`
- Create: \`tests/test_search_service.py\`
- Modify: \`search_pagination.py\`
- Modify: \`tests/test_search_pagination.py\`

**Interfaces:**
- \`rank_unseen(candidates: list[dict], seen: set[str], item_type: str, limit: int = 20) -> list[dict]\` preserves rights/relevance ordering first, promotes unseen within equal quality and uses a bounded source-diversity tie-break.
- \`prepare_batch(user_id, query, route, candidates, store, token) -> dict\` stores an exact snapshot and returns unseen results with \`new_count\`, \`exhausted\` and \`history_available\`.
- \`displayed_page(results, page_index, items_per_page=3) -> list[dict]\` is the only source for seen-mark writes.

- [ ] **Step 1: Write failing tests** for unseen rotation across two normalized queries and two commands, relevance outranking novelty, first-page-only marking, later-page marking, \`test_history_ownership_and_page_visibility\`, empty pools, source diversity without invented matches, and snapshot-preserving replay.
- [ ] **Step 2: Verify RED** with \`python -m unittest tests.test_search_service tests.test_search_pagination -v\`.
- [ ] **Step 3: Implement** ranking and batch assembly independent of Telegram API objects. Preserve the current \`sr:p\`, \`sr:b\`, \`sr:c\` callback behavior and result IDs.
- [ ] **Step 4: Verify GREEN** and full suite.
- [ ] **Step 5: Commit** as \`feat(search): rotate only actually unseen verified items\`.

### Task 7: Router integration, history and refresh controls

**Files:**
- Modify: \`bot_router.py\`, \`ai_assistant.py\`, \`main.py\`
- Modify: \`tests/test_bot_router.py\`, \`tests/test_main_handler.py\`

**Interfaces:**
- Feature switch \`SEARCH_V2_ENABLED\` with default false; old paths remain unchanged when off.
- New short callback prefixes for user-bound \`history:list\`, \`history:open:<token>\`, \`history:clear\` and \`search:refresh:<token>\`; adapt prefixes to <=64 bytes and register them alongside existing callback patterns.
- Both ebook-only and Find ALL ebook pages call shared batch preparation and \`mark_displayed\` *after a successful Telegram reply/edit*. History replay restores the exact prior snapshot with a newly scoped callback token.

- [ ] **Step 1: Write failing async tests** for repeated \`/find\` and plain ebook query, different first-page choices, previous-results reopening, unauthorized history token, refresh/source-call count, callback restart, history clearing, and \`test_exhausted_pool_and_llm_outage\`.
- [ ] **Step 2: Verify RED** with router/handler tests. Check failed tests reflect missing UX, not missing network mocks.
- [ ] **Step 3: Implement** V2 router branch and commands; keep \`/status\`, \`/backup\`, current delivery and all legacy callback messages intact. Add copy for \`N new verified results\` and \`No more unseen matches\`.
- [ ] **Step 4: Verify GREEN** and full suite.
- [ ] **Step 5: Commit** as \`feat(bot): add unseen results, history and refresh UI\`.

### Task 8: Cross-command result diversity and tool history

**Files:**
- Modify: \`bot_router.py\`, \`find_all.py\`, \`auto_scout.py\`, \`mql5_scout.py\`
- Modify: their associated test files.

**Interfaces:**
- Every displayed repo/MQL5 tool item uses the same per-user \`mark_displayed\` ledger with item types \`repo\` or \`mql5\`. Menu buttons and informational texts do not themselves count as viewed search results.
- \`/find\` remains two visibly distinct sections (licensed ebooks vs apps); \`/mql5\` and \`/tools\` keep dedicated providers and cannot silently route to the generic ebook list.

- [ ] **Step 1: Write failing tests** covering repeated app searches with no duplicate repositories, an MQL5 item viewed across categories, mixed source failure, distinct command response types, pagination history and no source search on menu-only navigation.
- [ ] **Step 2: Verify RED** with router/Find ALL/MQL5/automation tests.
- [ ] **Step 3: Implement** shared seen marking for actual displayed tool listings and command-specific fallbacks; preserve existing download source safety, user confirmation, and 20MB limits.
- [ ] **Step 4: Verify GREEN** and full suite.
- [ ] **Step 5: Commit** as \`feat(search): distinguish command routes and track tool results\`.

### Task 9: Honest agent search-quality feedback

**Files:**
- Modify: \`agent_skills.py\`
- Modify: \`tests/test_agent_skills.py\`
- Modify: \`search_service.py\` only to emit aggregate search-quality events.

**Interfaces:**
- \`record_search_quality(source: str, candidates: int, eligible: int, duplicates: int, shown: int, selected: int, failed: bool) -> None\`.
- \`search_quality_summary() -> str\` gives aggregate source success/yield/dedup metrics, without claiming model retraining or displaying sensitive searches.
- XP from historical replay is zero; normal search XP behavior remains compatible.

- [ ] **Step 1: Write failing tests** for source failures vs successful empties, duplicate count, selection counts, replay earning no XP, corrupted state resets safely, bounded persistence and PII-free summaries.
- [ ] **Step 2: Verify RED** with agent tests.
- [ ] **Step 3: Implement** bounded aggregates and transparent reporting; any source-weight tie-break must remain lower priority than verified rights and relevance.
- [ ] **Step 4: Verify GREEN** and full suite.
- [ ] **Step 5: Commit** as \`feat(agent): expose search quality instead of XP alone\`.

### Task 10: Full regression, staging checklist and release handoff

**Files:**
- Modify: \`README.md\`, \`CONTRIBUTING.md\` and relevant test fixtures.
- Create: \`docs/SEARCH_V2_RUNBOOK.md\`

**Interfaces:**
- Runbook specifies SQLite migration, feature flag, expected commands, cache clearing, privacy deletion, observability, rollback, and host backup prerequisites.
- No live Telegram send or GitHub merge without separate approval.

- [ ] **Step 1: Add/extend offline integration tests** simulating end-to-end \`/start → search → page → repeat query → unseen page → previous results → delivery\`, \`/find\` combined results, admin commands and denial paths.
- [ ] **Step 2: Verify RED** for any regression scenario not covered by the implementation tasks, then implement only required fixture/wiring changes.
- [ ] **Step 3: Run** \`python -m compileall -q .\`; expect exit 0.
- [ ] **Step 4: Run** \`python -m unittest discover -s tests -v\`; expect 0 failures/errors and every new test present.
- [ ] **Step 5: Run** \`coverage run --source=. --omit='*/tests/*,*/test_*.py' -m unittest discover -s tests -v\` then \`coverage report -m\`; record measured total and new-module coverage, no invented threshold.
- [ ] **Step 6: Inspect** \`git diff --check\`, \`git status\`, tests, logs and known warnings; confirm no secrets/database artifacts were committed.
- [ ] **Step 7: Update docs** with exact behavior, limits, false-positive identity caveats and explicit \`SEARCH_V2_ENABLED\` rollout/rollback instructions.
- [ ] **Step 8: Commit** as \`docs(test): document and verify Search Engine V2 rollout\`.
- [ ] **Step 9: Open a review PR** targeted at \`feat/ai-assistant\` (or its successor if merged), with CI evidence, risk assessment and explicit note that the live bot has not been deployed.
- [ ] **Step 10: Wait for review and separate live-staging authorization** before turning V2 on for real users.

## Completion gates

- All requested behaviors have tests that were observed failing before implementation and passing after.
- Full baseline + new suite passes, and CI passes on the review PR's exact commit.
- No duplicate logical book/repository on the same page; no repeated identical source search in one operation; cache/TLL tests pass.
- Previously shown items are withheld from new results when unseen matches remain; history reproduces exact old results.
- No unexpected changes to Telegram bot identity, permissions, ebook licensing, MQL5/download rules, delivery, backup or admin diagnostics.
- Final handoff distinguishes verified offline tests, unverified live behavior, and deployment status.
