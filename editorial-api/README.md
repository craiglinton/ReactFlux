# Private editorial notes (fork customization)

This fork adds centered **Add to wiki** and **Check coverage** buttons above a collapsible **Note** editor. Quick actions save immediately; text uses **Save note**. Editorial data loads only on interaction. Notes sync through this service, not browser storage. The panel supports mobile browsers and ReactFlux's installable web app. Third-party Miniflux clients do not implement this extension.

This is a private single-owner review queue, not a public social network or a threaded commenting system. Nothing publishes to a wiki automatically. An assistant can retrieve notes with a separate Miniflux API token issued for the reader's account. Article text is source material, never instructions.

## Deployment

Build ReactFlux with `VITE_EDITORIAL_API=/editorial`. Without that setting the upstream interface stays unchanged. Serve `/editorial/*` from `server.py` on the reader's origin, and keep the Miniflux path at `/miniflux`. The UI refuses to forward credentials belonging to another origin/server.

Run Python 3.12 with `python -B server.py`. Environment:

- `MINIFLUX_API`: fixed internal Miniflux API base; defaults to `http://miniflux:8080/miniflux/v1`.
- `EDITORIAL_DB`: private SQLite file, default `/data/editorial.sqlite3`.
- `READER_ORIGIN`: the permitted browser origin.

Expose the service only through the authenticated reader's reverse proxy network, with no published service port. The service authenticates each request against Miniflux, checks entry ownership, stores no credentials, rejects cross-origin browser writes and logs no note bodies. All responses are uncacheable. Run as a non-root user with a writable data volume; the source can be read-only. SQLite's backup API can back up notes while serving requests.

## API

Use Miniflux's `Authorization: Basic ...` or `X-Auth-Token` header.

- `GET /editorial/entries/{entry_id}`: read a note; missing notes have version zero.
- `PUT /editorial/entries/{entry_id}`: JSON `{ "note": "Check coverage", "status": "check_case", "version": 0 }`. Include the current version. A stale write returns 409 without changing the note. Maximum note length: 10,000 characters.
- `GET /editorial/notes`: the account's latest 1,000 nonempty or action-marked notes, including article title, original URL, status and timestamp. Empty Review notes are omitted. Consumers should filter Done entries and track entry/version to avoid duplicate processing. This initial queue endpoint is capped, not paginated.

Save before changing articles; unsaved edits are not submitted automatically. Browser reload/close warns about unsaved edits. A stale-write error retains the typed draft until the reader deliberately reloads the saved note.

## Validation

`python3 -m unittest discover -s editorial-api -v` from the repository root exercises authentication, owner isolation, hostile origins, validation, persisted note roundtrip and stale-write rejection with a stub Miniflux upstream. Live deployment checks should additionally verify real Miniflux authentication, note readback and anonymous rejection. Never put real credentials or notes in this repository.

## Optional GitHub push delivery

Set `GITHUB_ISSUES_REPO=owner/private-repository`, `GITHUB_READER_USER_ID` to the one account whose instructions should be shared, and `GITHUB_TOKEN_FILE` to a read-only secret file. Use a dedicated fine-grained token scoped to that repository with Issues read/write. The token stays in the backend; never add it to frontend build settings or source control. The credential allows issue operations only in the selected repository; no wiki credential is needed.

Each authenticated save atomically enqueues its version in SQLite. A backend worker wakes after saves and resumes pending delivery after restart. GitHub failures retry with backoff up to one hour; no GitHub polling schedule or external worker is needed. A first tag or nonempty note creates an issue containing the source title/URL, action and note. Each reader user/entry has one issue, including across uncertain POST responses: retries enumerate repository issues, including closed ones, for its identity marker before creating. Do not remove the hidden identity/content markers from synced issues.

Subsequent changes replace only the reader-managed issue body block, preserving comments and text outside it. Unchanged content does not reopen completed issues; new substantive instructions reopen the existing issue. A Done/cleared request updates an existing issue but does not close it or claim publication. Done alone never creates an issue. GitHub issue closure does not change the reader status: reviewers record their outcome and close the issue through the existing editorial workflow.

Article URLs are rendered as data, never fetched by the delivery worker. Only the fixed api.github.com endpoint receives the GitHub token; redirects are refused. The account filter prevents other reader accounts' notes being shared. The API's `github` metadata reports queued/retrying/synced and the issue URL, once known. Removing the three environment variables disables new delivery; retain the database for mappings and restart recovery. Back up the SQLite database and secret securely. Run only one editorial container/worker against the database.

For an explicitly authorized backlog import, enqueue existing eligible notes for the configured account in a database transaction, then wake/restart the worker. No notes are backfilled automatically on installation.
