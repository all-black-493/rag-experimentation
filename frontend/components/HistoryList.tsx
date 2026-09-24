"use client";

import { X } from "lucide-react";
import { byDay, type Conversation } from "@/lib/history";

interface Props {
  conversations: Conversation[];
  currentId: string | null;
  onOpen: (conversation: Conversation) => void;
  onRemove: (id: string) => void;
}

/**
 * Every question asked from this browser, newest first, under the day it was
 * asked. The question itself is the label - a research desk keeps the
 * question, not a title someone invented for it.
 */
export function HistoryList({ conversations, currentId, onOpen, onRemove }: Props) {
  if (conversations.length === 0) {
    return <p className="px-2 py-1 text-sm text-ink-3">Nothing asked yet.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {byDay(conversations).map(([day, entries]) => (
        <section key={day}>
          <h3 className="px-2 pb-1 font-mono text-[0.6875rem] uppercase tracking-[0.08em] text-ink-3">
            {day}
          </h3>
          <ul>
            {entries.map((conversation) => {
              const active = conversation.id === currentId;
              return (
                <li key={conversation.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onOpen(conversation)}
                    aria-current={active ? "true" : undefined}
                    className={[
                      "press block w-full truncate rounded-control py-1.5 pl-2 pr-8 text-left text-sm transition-colors duration-150",
                      active ? "bg-rule-2 text-ink" : "text-ink-2 hover:bg-paper-2 hover:text-ink",
                    ].join(" ")}
                  >
                    {conversation.question}
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemove(conversation.id)}
                    aria-label={`Forget "${conversation.question}"`}
                    className="absolute right-1 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-control text-ink-3 opacity-0 transition-opacity duration-150 hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
