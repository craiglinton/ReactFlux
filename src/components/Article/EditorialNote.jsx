import { Button, Input } from "@arco-design/web-react"
import { useStore } from "@nanostores/react"
import { useEffect, useState } from "react"

import { authState } from "@/store/authState"
import "./EditorialNote.css"

const endpoint = import.meta.env.VITE_EDITORIAL_API
const actions = [
  { value: "add_to_wiki", label: "Add to wiki" },
  { value: "check_case", label: "Check coverage" },
]

const request = async (entryId, auth, data) => {
  const headers = auth.token
    ? { "X-Auth-Token": auth.token }
    : { Authorization: `Basic ${btoa(`${auth.username}:${auth.password}`)}` }
  const response = await fetch(`${endpoint}/entries/${entryId}`, {
    method: data ? "PUT" : "GET",
    headers: { ...headers, "Content-Type": "application/json" },
    body: data ? JSON.stringify(data) : undefined,
    cache: "no-store",
  })
  const result = await response.json()
  if (!response.ok) {
    throw new Error(result.error || "Unable to load editorial notes.")
  }
  return result
}

function NoteEditor({ entryId, auth }) {
  const [saved, setSaved] = useState(null)
  const [note, setNote] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const [reload, setReload] = useState(0)
  const dirty = saved && note !== saved.note

  useEffect(() => {
    let cancelled = false
    request(entryId, auth)
      .then((result) => {
        if (cancelled) {
          return null
        }
        setSaved(result)
        setNote(result.note)
        setError("")
        return null
      })
      .catch((error_) => {
        if (!cancelled) {
          setError(error_.message)
        }
      })
    return () => {
      cancelled = true
    }
  }, [entryId, auth, reload])

  useEffect(() => {
    if (!dirty) {
      return
    }
    const warn = (event) => {
      event.preventDefault()
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirty])

  const save = async (action) => {
    setBusy(action)
    setError("")
    try {
      const result = await request(entryId, auth, {
        note: action === "note" ? note : saved.note,
        status: action === "note" ? saved.status : action,
        version: saved.version,
      })
      setSaved(result)
    } catch (error_) {
      setError(error_.message)
    } finally {
      setBusy("")
    }
  }

  return (
    <section aria-label="Editorial actions" className="editorial-note">
      <div className="editorial-quick-actions">
        {actions.map((action) => (
          <Button
            key={action.value}
            aria-pressed={saved?.status === action.value}
            disabled={!saved || Boolean(busy)}
            loading={busy === action.value}
            type={saved?.status === action.value ? "primary" : "secondary"}
            onClick={() => save(action.value)}
          >
            {action.label}
          </Button>
        ))}
        <span aria-live="polite">
          {busy && busy !== "note"
            ? "Saving…"
            : saved?.status === "done"
              ? "Done"
              : actions.some((action) => action.value === saved?.status)
                ? "Saved"
                : ""}
        </span>
      </div>
      <details>
        <summary>
          Note
          {(dirty || saved?.note) && (
            <span className="editorial-note-badge">{dirty ? "Unsaved changes" : "Saved note"}</span>
          )}
        </summary>
        <p className="editorial-note-help">
          Add instructions for wiki review. Save before moving to another article.
        </p>
        {saved && (
          <>
            <label htmlFor={`editorial-text-${entryId}`}>Note</label>
            <Input.TextArea
              autoSize={{ minRows: 3, maxRows: 8 }}
              disabled={Boolean(busy)}
              id={`editorial-text-${entryId}`}
              maxLength={10_000}
              placeholder="Add a more detailed instruction…"
              value={note}
              onChange={setNote}
            />
            <div className="editorial-note-actions">
              <Button
                disabled={!dirty || Boolean(busy)}
                loading={busy === "note"}
                type="primary"
                onClick={() => save("note")}
              >
                Save note
              </Button>
              <span aria-live="polite">
                {busy === "note" ? "Saving…" : dirty ? "Unsaved changes" : "Saved"}
              </span>
            </div>
          </>
        )}
      </details>
      {!saved && !error && <p>Loading editorial actions…</p>}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <Button disabled={Boolean(busy)} onClick={() => setReload((value) => value + 1)}>
            Reload saved note
          </Button>
        </div>
      )}
    </section>
  )
}

export default function EditorialNote({ entryId }) {
  const auth = useStore(authState)
  if (!endpoint) {
    return null
  }
  // This optional service belongs to this reader deployment only. Never send
  // credentials for another Miniflux server to it.
  let server
  try {
    server = new URL(auth.server)
  } catch {
    return null
  }
  if (
    server.origin !== globalThis.location.origin ||
    server.pathname.replace(/\/$/, "") !== "/miniflux"
  ) {
    return null
  }
  return (
    <NoteEditor key={`${entryId}:${auth.username}:${auth.token}`} auth={auth} entryId={entryId} />
  )
}
