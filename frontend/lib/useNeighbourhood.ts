"use client";

import { useEffect, useState } from "react";
import { fetchNeighbourhood } from "./api";
import type { GraphNeighbourhood } from "./types";

// The graph is static between ingests; a document's neighbourhood is fetched once per session.
const cache = new Map<string, Promise<GraphNeighbourhood | null>>();

function load(docId: string): Promise<GraphNeighbourhood | null> {
  let pending = cache.get(docId);
  if (!pending) {
    pending = fetchNeighbourhood(docId).catch(() => {
      cache.delete(docId);
      return null;
    });
    cache.set(docId, pending);
  }
  return pending;
}

/** The citation neighbourhood of one document; null while loading or when none is recorded. */
export function useNeighbourhood(docId: string | null): GraphNeighbourhood | null {
  // Keyed by document so a stale answer never shows under the next authority.
  const [loaded, setLoaded] = useState<{ docId: string; data: GraphNeighbourhood | null } | null>(null);

  useEffect(() => {
    if (!docId) return;
    let live = true;
    load(docId).then((data) => {
      if (live) setLoaded({ docId, data });
    });
    return () => {
      live = false;
    };
  }, [docId]);

  return loaded?.docId === docId ? loaded.data : null;
}
