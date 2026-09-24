"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createMatter,
  deleteDocument,
  fetchMatter,
  followMatter,
  listMatters,
  uploadDocument,
} from "./api";
import type { Matter } from "./types";

const STORAGE_KEY = "wakili.matter";

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function remember(id: string | null) {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // A private window or blocked storage: the choice just doesn't survive a reload.
  }
}

/**
 * The matters this browser can see and the one in use. While a document of the
 * current matter is still being indexed, the server streams the matter as its
 * state moves, so the rail shows the status change without a refresh and
 * without asking.
 */
export function useMatter() {
  const [matters, setMatters] = useState<Matter[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loaded = useRef(false);

  const current = matters.find((m) => m.id === currentId) ?? null;
  const pending = current?.documents.some((d) => d.status === "queued" || d.status === "running") ?? false;

  const replace = useCallback((matter: Matter) => {
    setMatters((all) => (all.some((m) => m.id === matter.id) ? all.map((m) => (m.id === matter.id ? matter : m)) : [matter, ...all]));
  }, []);

  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    listMatters()
      .then((all) => {
        setMatters(all);
        const wanted = remembered();
        if (wanted && all.some((m) => m.id === wanted)) setCurrentId(wanted);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!currentId || !pending) return;
    const controller = new AbortController();
    (async () => {
      try {
        for await (const matter of followMatter(currentId, controller.signal)) {
          replace(matter);
        }
      } catch {
        // The stream is how the status arrives, not how it is established:
        // if it drops, one read still leaves the rail correct.
        if (!controller.signal.aborted) {
          fetchMatter(currentId).then(replace).catch(() => undefined);
        }
      }
    })();
    return () => controller.abort();
  }, [currentId, pending, replace]);

  const select = useCallback((id: string | null) => {
    setCurrentId(id);
    remember(id);
  }, []);

  const create = useCallback(
    async (name: string) => {
      const matter = await createMatter(name);
      replace(matter);
      select(matter.id);
      return matter;
    },
    [replace, select],
  );

  const upload = useCallback(
    async (files: FileList | File[]) => {
      if (!currentId) return;
      setError(null);
      for (const file of Array.from(files)) {
        try {
          await uploadDocument(currentId, file);
        } catch (e) {
          setError((e as Error).message);
        }
      }
      fetchMatter(currentId).then(replace).catch(() => undefined);
    },
    [currentId, replace],
  );

  const refresh = useCallback(() => {
    if (currentId) fetchMatter(currentId).then(replace).catch(() => undefined);
  }, [currentId, replace]);

  const remove = useCallback(
    async (docId: string) => {
      if (!currentId) return;
      await deleteDocument(currentId, docId);
      fetchMatter(currentId).then(replace).catch(() => undefined);
    },
    [currentId, replace],
  );

  return { matters, current, pending, error, select, create, upload, remove, refresh };
}
