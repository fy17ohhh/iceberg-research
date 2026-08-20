"use client";

import { useState } from "react";
import { useLanguage } from "@/lib/i18n";

export default function QueryInput({
  onSubmit,
  disabled,
}: {
  onSubmit: (query: string) => void;
  disabled?: boolean;
}) {
  const { t } = useLanguage();
  const [query, setQuery] = useState("");

  function handleSubmit() {
    const trimmed = query.trim();
    if (trimmed) {
      onSubmit(trimmed);
    }
  }

  return (
    <div className="relative w-full max-w-2xl">
      <textarea
        value={query}
        disabled={disabled}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        placeholder={t("researchQuestionPlaceholder")}
        rows={3}
        className="research-input w-full rounded-2xl border px-5 py-4 pr-14 text-foreground font-mono placeholder:text-muted-foreground/65 placeholder:font-mono resize-none focus:outline-none transition-all"
      />
      <button
        onClick={handleSubmit}
        disabled={disabled || !query.trim()}
        aria-label={t("submitResearch")}
        className="launch-button absolute right-2.5 bottom-4 rounded-xl bg-accent p-2.5 text-white hover:bg-accent-hover active:scale-90 disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-150"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-5 h-5"
        >
          <path d="M5 12h14M12 5l7 7-7 7" />
        </svg>
      </button>
    </div>
  );
}
