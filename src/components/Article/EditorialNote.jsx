import { Button, Input, Select } from "@arco-design/web-react"
import { useStore } from "@nanostores/react"
import { useEffect, useState } from "react"

import { authState } from "@/store/authState"
import "./EditorialNote.css"

const endpoint = import.meta.env.VITE_EDITORIAL_API
const statuses = [
  { value: "review", label: "Review" },
  { value: "add_to_wiki", label: "Add to wiki" },
  { value: "check_case", label: "Check case coverage" },
  { value: "done", label: "Done" },
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
  const [status, setStatus] = useState("review")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const dirty = saved && (note !== saved.note || status !== saved.status)

  useEffect(() => {
    let cancelled = false
    request(entryId, auth)
      .then((result) => {
        if (cancelled) {
          return null
        }
        setSaved(result)
        setNote(result.note)
        setStatus(result.status)
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

  const save = async () => {
    setBusy(true)
    setError("")
    try {
      const result = await request(entryId, auth, { note, status, version: saved.version })
      setSaved(result)
    } catch (error_) {
      setError(error_.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="editorial-note">
      <summary>
        Editorial note
        {saved && (saved.note || saved.status !== "review") && (
          <span className="editorial-note-badge">
            {statuses.find((item) => item.value === saved.status)?.label}
          </span>
        )}
      </summary>
      <p className="editorial-note-help">
        Leave instructions for wiki review. Save before moving to another article.
      </p>
      {saved && (
        <>
          <label htmlFor={`editorial-text-${entryId}`}>Note</label>
          <Input.TextArea
            autoSize={{ minRows: 3, maxRows: 8 }}
            disabled={busy}
            id={`editorial-text-${entryId}`}
            maxLength={10_000}
            placeholder="For example: Check whether this case has an entry."
            value={note}
            onChange={setNote}
          />
          <div className="editorial-note-actions">
            <Select
              aria-label="Review status"
              disabled={busy}
              options={statuses}
              value={status}
              onChange={setStatus}
            />
            <Button disabled={!dirty} loading={busy} type="primary" onClick={save}>
              Save note
            </Button>
            <span aria-live="polite">{busy ? "Saving…" : dirty ? "Unsaved changes" : "Saved"}</span>
          </div>
        </>
      )}
      {!saved && !error && <p>Loading note…</p>}
      {error && (
        <div role="alert">
          <p>{error}</p>
          <Button disabled={busy} onClick={() => setReload((value) => value + 1)}>
            Reload saved note
          </Button>
        </div>
      )}
    </details>
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
