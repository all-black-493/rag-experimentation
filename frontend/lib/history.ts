"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { ResearchState } from "./useResearch";

/**
 * The questions this browser has asked, so you can go back to one.
 *
 * Kept in the browser rather than on the server: there are no accounts here,
 * and a conversation is a reading of the corpus rather than a record of it -
 * the matter, which is a record, is on disk. The whole finished state is
 * stored, so reopening a conversation puts back the answer and its
 * authorities without asking the model anything a second time.
 *
 * `localStorage` is read through `useSyncExternalStore` rather than in an
 * effect: it is external state, the server has none of it, and the snapshot
 * has to be the same object each time or React re-renders forever.
 */
const KEY = "wakili.history";
// Enough to find last week's question; small enough that the store stays
// well inside a browser's few megabytes even with the passages kept.
const LIMIT = 40;

export interface Conversation {
  id: string;
  question: string;
  at: number;
  matterId: string | null;
  state: ResearchState;
}

const NONE: Conversation[] = [];
let cache: { raw: string | null; value: Conversation[] } = { raw: null, value: NONE };
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Another tab writing the same store is this tab's history too.
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function snapshot(): Conversation[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    return NONE;
  }
  if (raw === cache.raw) return cache.value;
  let value: Conversation[] = NONE;
  try {
    const parsed = raw ? JSON.parse(raw) : [];
    if (Array.isArray(parsed)) value = parsed;
  } catch {
    // A store written by an older shape: start again rather than crash.
  }
  cache = { raw, value };
  return value;
}

function write(conversations: Conversation[]): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(conversations));
  } catch {
    // A full or blocked store costs the history, not the answer on screen.
  }
  for (const listener of listeners) listener();
}

/** Newest first, with the tools to add to it, reopen one, or forget one. */
export function useHistory() {
  const conversations = useSyncExternalStore(subscribe, snapshot, () => NONE);

  const save = useCallback((question: string, state: ResearchState, matterId: string | null) => {
    const entry: Conversation = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      question,
      at: Date.now(),
      matterId,
      state,
    };
    write([entry, ...snapshot()].slice(0, LIMIT));
    return entry.id;
  }, []);

  const remove = useCallback((id: string) => {
    write(snapshot().filter((conversation) => conversation.id !== id));
  }, []);

  return { conversations, save, remove };
}

/**
 * "Today", "Yesterday", then the date - the way you would look for a note you
 * made, rather than a timestamp you would have to decode.
 */
export function dayOf(at: number): string {
  const then = new Date(at);
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (at >= midnight) return "Today";
  if (at >= midnight - 86_400_000) return "Yesterday";
  return then.toLocaleDateString("en-KE", {
    day: "numeric",
    month: "short",
    year: then.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

/** The conversations in order, split under the day they were asked. */
export function byDay(conversations: Conversation[]): Array<[string, Conversation[]]> {
  const days = new Map<string, Conversation[]>();
  for (const conversation of conversations) {
    const day = dayOf(conversation.at);
    const bucket = days.get(day);
    if (bucket) bucket.push(conversation);
    else days.set(day, [conversation]);
  }
  return [...days];
}

/**
 * Whether the sidebar is folded away. A preference about this screen, so it
 * outlives the tab - and external state, so it is read the same way.
 */
const FOLD_KEY = "wakili.sidebar";
let folded = false;
const foldListeners = new Set<() => void>();

function subscribeFold(listener: () => void): () => void {
  foldListeners.add(listener);
  return () => foldListeners.delete(listener);
}

export function useSidebarFold(): [boolean, () => void] {
  const collapsed = useSyncExternalStore(
    subscribeFold,
    () => {
      try {
        folded = window.localStorage.getItem(FOLD_KEY) === "1";
      } catch {
        // Blocked storage: the column starts open and stays that way.
      }
      return folded;
    },
    () => false,
  );

  const toggle = useCallback(() => {
    folded = !folded;
    try {
      window.localStorage.setItem(FOLD_KEY, folded ? "1" : "0");
    } catch {
      // The fold still works for this session.
    }
    for (const listener of foldListeners) listener();
  }, []);

  return [collapsed, toggle];
}
