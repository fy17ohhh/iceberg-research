"use client";

import { useState } from "react";
import {
  DEFAULT_RESEARCH_PREFERENCES,
  getClientSessionId,
  getResearchPreferences,
  saveResearchPreferences,
  type ResearchPreferences,
} from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

export default function ResearchPreferencesDrawer() {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [preferences, setPreferences] = useState<ResearchPreferences>(
    DEFAULT_RESEARCH_PREFERENCES,
  );
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  function handleOpen() {
    setOpen(true);
    setLoading(true);
    setError("");
    getResearchPreferences()
      .then(setPreferences)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }

  function update<K extends keyof ResearchPreferences>(
    key: K,
    value: ResearchPreferences[K],
  ) {
    setSaved(false);
    setPreferences((current) => ({ ...current, [key]: value }));
  }

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      setPreferences(
        await saveResearchPreferences(preferences, getClientSessionId()),
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2200);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <button
        onClick={handleOpen}
        className="floating-control preferences-control"
      >
        <MemoryIcon />
        {t("preferences")}
      </button>

      <div
        className={`fixed inset-0 z-50 transition-colors duration-300 ${
          open ? "bg-foreground/5 pointer-events-auto" : "pointer-events-none"
        }`}
        onClick={() => setOpen(false)}
      />

      <aside
        className={`fixed right-0 top-0 bottom-0 z-50 w-full max-w-md bg-surface border-l border-foreground/8 shadow-lg flex flex-col transition-transform duration-350 ease-[cubic-bezier(0.2,0.8,0.2,1)] ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <header className="flex items-start justify-between px-6 pt-6 pb-4 border-b border-foreground/7">
          <div>
            <h2 className="text-[16px] font-medium">{t("longTermPreferences")}</h2>
            <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
              {t("preferencesDescription")}
            </p>
          </div>
          <button
            onClick={() => setOpen(false)}
            className="p-1 text-muted-foreground hover:text-foreground active:scale-90"
            aria-label={t("close")}
          >
            <CloseIcon />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto thin-scroll px-6 py-5">
          {loading ? (
            <p className="text-[13px] text-muted-foreground">{t("loadingMemory")}</p>
          ) : (
            <div className="space-y-6">
              <SettingSection title={t("reportStyle")}>
                <SelectRow
                  label={t("reportLanguage")}
                  value={preferences.report_language}
                  onChange={(value) =>
                    update("report_language", value as ResearchPreferences["report_language"])
                  }
                  options={[
                    ["auto", t("followQuestionLanguage")],
                    ["zh-CN", t("chineseLanguage")],
                    ["en", t("english")],
                  ]}
                />
                <SelectRow
                  label={t("analysisDepth")}
                  value={preferences.report_depth}
                  onChange={(value) =>
                    update("report_depth", value as ResearchPreferences["report_depth"])
                  }
                  options={[
                    ["concise", t("concise")],
                    ["balanced", t("balanced")],
                    ["deep", t("deep")],
                  ]}
                />
              </SettingSection>

              <SettingSection title={t("sourceStrategy")}>
                <ToggleRow
                  label={t("preferPrimary")}
                  description={t("primaryDescription")}
                  checked={preferences.prefer_primary_sources}
                  onChange={(value) => update("prefer_primary_sources", value)}
                />
                <ToggleRow
                  label={t("preferAcademic")}
                  description={t("academicDescription")}
                  checked={preferences.prefer_academic_sources}
                  onChange={(value) => update("prefer_academic_sources", value)}
                />
                <ToggleRow
                  label={t("includeCode")}
                  description={t("codeDescription")}
                  checked={preferences.include_code_repositories}
                  onChange={(value) => update("include_code_repositories", value)}
                />
              </SettingSection>

              <SettingSection title={t("evidenceDetail")}>
                <ToggleRow
                  label={t("includeMethodology")}
                  description={t("methodologyDescription")}
                  checked={preferences.include_methodology}
                  onChange={(value) => update("include_methodology", value)}
                />
                <ToggleRow
                  label={t("includeQuantitative")}
                  description={t("quantitativeDescription")}
                  checked={preferences.include_quantitative_evidence}
                  onChange={(value) =>
                    update("include_quantitative_evidence", value)
                  }
                />
              </SettingSection>

              <SettingSection title={t("researchBackground")}>
                <p className="text-[12px] text-muted-foreground leading-relaxed mb-2">
                  {t("contextDescription")}
                </p>
                <textarea
                  rows={5}
                  value={preferences.research_context}
                  onChange={(event) =>
                    update("research_context", event.target.value)
                  }
                  placeholder={t("contextPlaceholder")}
                  className="w-full rounded-xl bg-background/55 border border-foreground/12 px-3.5 py-3 text-[13px] leading-relaxed resize-none focus:outline-none focus:border-foreground/30"
                />
              </SettingSection>

              <div className="rounded-xl bg-background/55 border border-foreground/8 px-3.5 py-3">
                <p className="text-[12px] text-foreground/70 leading-relaxed">
                  {t("memoryDescription")}
                </p>
              </div>
            </div>
          )}
        </div>

        <footer className="px-6 py-4 border-t border-foreground/7">
          {error && <p className="text-[12px] text-error mb-2">{error}</p>}
          <button
            onClick={handleSave}
            disabled={loading || saving}
            className="w-full rounded-xl bg-accent text-surface py-2.5 text-[13px] font-medium hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50 transition-all"
          >
            {saving ? t("savingPreferences") : saved ? t("preferencesSaved") : t("savePreferences")}
          </button>
        </footer>
      </aside>
    </>
  );
}

function SettingSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="text-[12px] uppercase tracking-wider text-muted-foreground mb-2.5">
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function SelectRow({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <label className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-[13px]">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg bg-background/65 border border-foreground/10 px-2.5 py-1.5 text-[12px] focus:outline-none"
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-4 rounded-xl px-3 py-2.5 hover:bg-background/45 cursor-pointer">
      <span>
        <span className="block text-[13px]">{label}</span>
        <span className="block text-[11px] text-muted-foreground mt-0.5">
          {description}
        </span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 accent-[var(--accent)]"
      />
    </label>
  );
}

function MemoryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
      <path d="M9 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
      <path d="M10 8h4M10 12h4M10 16h3" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" className="w-4 h-4">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}
