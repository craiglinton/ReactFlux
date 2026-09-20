import { Button, Input } from "@arco-design/web-react"
import { useStore } from "@nanostores/react"
import { useEffect, useRef, useState } from "react"

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
  const pending = useRef(false)
  const dirty = saved && note !== saved.note

  const load = async () => {
    if (pending.current) {
      return
    }
    pending.current = true
    setBusy("load")
    setError("")
    try {
      const result = await request(entryId, auth)
      setSaved(result)
      setNote(result.note)
    } catch (error_) {
      setError(error_.message)
    } finally {
      pending.current = false
      setBusy("")
    }
  }

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
    if (pending.current) {
      return
    }
    pending.current = true
    setBusy(action)
    setError("")
    try {
      // Quick actions need the latest persisted note/version on first use, but
      // simply viewing an article should not fetch editorial data.
      const current = saved || (await request(entryId, auth))
      if (!saved) {
        setSaved(current)
        setNote(current.note)
      }
      const result = await request(entryId, auth, {
        note: action === "note" ? note : current.note,
        status: action === "note" ? current.status : action,
        version: current.version,
      })
      setSaved(result)
    } catch (error_) {
      setError(error_.message)
    } finally {
      pending.current = false
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
            disabled={Boolean(busy)}
            loading={busy === action.value}
            type={saved?.status === action.value ? "primary" : "secondary"}
            onClick={() => save(action.value)}
          >
            {action.label}
          </Button>
        ))}
        <span aria-live="polite">
          {busy && busy !== "note" && busy !== "load"
            ? "Saving…"
            : saved?.status === "done"
              ? "Done"
              : actions.some((action) => action.value === saved?.status)
                ? "Saved"
                : ""}
        </span>
      </div>
      <details
        onToggle={(event) => {
          if (event.currentTarget.open && !saved) {
            load()
          }
        }}
      >
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
        {!saved && !error && <p>Loading note…</p>}
      </details>
      {error && (
        <div role="alert">
          <p>{error}</p>
          <Button disabled={Boolean(busy)} onClick={load}>
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
