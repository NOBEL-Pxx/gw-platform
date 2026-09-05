// R6.27i: AI Models Hub floating button visibility state.
// Default: HIDDEN — the entire button is not rendered.
// User enables it via the navbar toggle (Layout.tsx).
//
// Renamed from R6.27h's `useSpinEnabled` because user clarified the
// semantics is about visibility, not animation. The hook is still pub/sub
// over localStorage so Layout (control) and AIFloatingButton (rendered
// subject) stay in sync across the React tree.

import { useEffect, useState, useCallback } from 'react'

const KEY = 'gw-ai-button-visible'

function readSnapshot(): boolean {
  try {
    return localStorage.getItem(KEY) === 'true'
  } catch {
    return false
  }
}

type Listener = (snap: boolean) => void
const listeners = new Set<Listener>()

function subscribe(l: Listener): () => void {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

function setSnapshot(next: boolean): void {
  try {
    localStorage.setItem(KEY, String(next))
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l(next))
}

export function useFloatingButtonVisible(): readonly [boolean, () => void] {
  const [snap, setSnap] = useState<boolean>(readSnapshot)

  useEffect(() => subscribe(setSnap), [])

  const toggle = useCallback(() => {
    setSnapshot(!readSnapshot())
  }, [])

  return [snap, toggle] as const
}
