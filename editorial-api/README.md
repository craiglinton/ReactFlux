# Private editorial notes (fork customization)

This fork adds a collapsible **Editorial note** panel to each article. Save a free-text note and choose Review, Add to wiki, Check case coverage, or Done. Notes sync through this service, not browser storage. The panel supports mobile browsers and ReactFlux's installable web app. Third-party Miniflux clients do not implement this extension.

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
