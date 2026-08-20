"use client";

import { useLanguage } from "@/lib/i18n";

/** A compact, always-active identity marker for research-agent messages. */
export default function AssistantStatus() {
  const { t } = useLanguage();

  return (
    <div
      className="assistant-status"
      aria-label={t("assistant")}
      title={t("assistant")}
    >
      <span className="submarine-emoji" role="img" aria-hidden="true">🛥️</span>
      <span className="assistant-status-dots" aria-hidden="true">
        {/* <i />
        <i />
        <i /> */}
      </span>
    </div>
  );
}
