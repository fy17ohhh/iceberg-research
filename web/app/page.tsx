"use client";

import { useEffect, useState } from "react";
import QueryInput from "@/components/QueryInput";
import LibraryDrawer from "@/components/LibraryDrawer";
import NavigatorPanel, { resetNavigatorCache } from "@/components/NavigatorPanel";
import ResearchProgress from "@/components/ResearchProgress";
import ReportView from "@/components/ReportView";
import ResearchPreferencesDrawer from "@/components/ResearchPreferencesDrawer";
import { LanguageProvider, LanguageSwitcher, useLanguage } from "@/lib/i18n";

export default function Home() {
  return (
    <LanguageProvider>
      <HomeContent />
    </LanguageProvider>
  );
}

function HomeContent() {
  const { t } = useLanguage();
  const [stage, setStage] = useState<"input" | "sending" | "navigating" | "researching" | "report">("input");
  const [query, setQuery] = useState("");
  const [brief, setBrief] = useState("");
  const [report, setReport] = useState("");
  const [stats, setStats] = useState<{ total_calls: number; total_tokens: number } | null>(null);
  const [exiting, setExiting] = useState(false);
  const [showExitConfirm, setShowExitConfirm] = useState(false);

  const hasActiveSearch = stage === "navigating" || stage === "researching";

  useEffect(() => {
    if (!hasActiveSearch) return;

    const guardState = { ...window.history.state, icebergSearchGuard: true };
    window.history.pushState(guardState, "", window.location.href);

    const handleBrowserBack = () => {
      window.history.pushState(guardState, "", window.location.href);
      setShowExitConfirm(true);
    };
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("popstate", handleBrowserBack);
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("popstate", handleBrowserBack);
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [hasActiveSearch]);

  function handleQuerySubmit(q: string) {
    setQuery(q);
    setStage("sending");
    setTimeout(() => setStage("navigating"), 400);
  }

  function handleBriefReady(b: string) {
    setBrief(b);
    setStage("researching");
  }

  function returnToSurface() {
    setShowExitConfirm(false);
    setExiting(true);
    setTimeout(() => {
      resetNavigatorCache();
      setStage("input");
      setBrief("");
      setReport("");
      setStats(null);
      setExiting(false);
    }, 350);
  }

  function handleBack() {
    if (hasActiveSearch) {
      setShowExitConfirm(true);
      return;
    }
    returnToSurface();
  }

  const isReport = stage === "report";
  const isLanding = stage === "input" || stage === "sending";

  return (
    <main className={`app-shell ${isLanding ? "is-landing" : "is-workspace"}`}>
      <div className="ambient-grid" aria-hidden="true" />

      {isLanding && (
        <>
          <LibraryDrawer />
          <ResearchPreferencesDrawer />
          <div className="flex flex-1 min-h-0 px-5 sm:px-10 lg:px-16">
            <HeroSection onSubmit={handleQuerySubmit} sending={stage === "sending"} />
          </div>
        </>
      )}

      {!isLanding && (
        <div className={`relative flex flex-1 w-full overflow-hidden min-h-0 ${exiting ? "back-exit" : ""}`}>
          <div
            className="transition-[flex] duration-700 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
            style={{ flex: isReport ? "0 0 0px" : "1 1 0px" }}
          />

          <section className="workspace-chat w-full max-w-3xl shrink-0 overflow-y-auto min-h-0 px-5 thin-scroll" data-scroll-container>
            <div className="sticky top-0 z-10 pointer-events-none -mx-5 px-5 workspace-fade" style={{ height: 58 }}>
              <button
                onClick={handleBack}
                className="pointer-events-auto mt-4 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/12 px-3 py-1.5 text-[12px] tracking-wide text-foreground/75 backdrop-blur-xl hover:bg-white/22 hover:text-foreground active:scale-95 transition-all duration-200"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
                  <path d="M19 12H5M12 19l-7-7 7-7" />
                </svg>
                {t("returnToSurface")}
              </button>
            </div>
            <div className="pb-8 gap-4 flex flex-col items-center">
              <NavigatorPanel query={query} onBriefReady={handleBriefReady} />
              {(stage === "researching" || isReport) && (
                <ResearchProgress
                  brief={brief}
                  onReport={(r, s) => {
                    setReport(r);
                    if (s) setStats({ total_calls: s.total_calls, total_tokens: s.total_tokens });
                    setStage("report");
                  }}
                />
              )}
            </div>
          </section>

          <section
            data-report-panel
            className={`report-glass flex-1 min-w-0 overflow-y-auto min-h-0 thin-scroll transition-opacity duration-500 ease-out ${
              isReport ? "opacity-100 border-l border-white/20" : "opacity-0 pointer-events-none"
            }`}
          >
            {report && <ReportView report={report} stats={stats} />}
          </section>
        </div>
      )}

      {showExitConfirm && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/55 px-5 backdrop-blur-md"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setShowExitConfirm(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="exit-research-title"
            className="w-full max-w-sm rounded-[28px] border border-white/25 bg-slate-950/80 p-6 text-white shadow-2xl shadow-cyan-950/40"
          >
            <h2 id="exit-research-title" className="text-xl font-semibold tracking-tight">
              {t("exitResearch")}
            </h2>
            <p className="mt-2 text-sm leading-6 text-white/65">
              {t("exitDescription")}
            </p>
            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={() => setShowExitConfirm(false)}
                className="flex-1 rounded-full border border-white/20 bg-white/10 px-4 py-2.5 text-sm font-medium transition hover:bg-white/20"
              >
                {t("continueResearch")}
              </button>
              <button
                type="button"
                onClick={returnToSurface}
                className="flex-1 rounded-full bg-cyan-300 px-4 py-2.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 active:scale-[0.98]"
              >
                {t("confirmExit")}
              </button>
            </div>
          </section>
        </div>
      )}
      <LanguageSwitcher />
    </main>
  );
}

function HeroSection({ onSubmit, sending }: { onSubmit: (q: string) => void; sending?: boolean }) {
  return (
    <div className={`hero-layout flex flex-1 w-full items-center justify-center ${sending ? "hero-exit" : ""}`}>
      <section className="hero-console hero-console-minimal">
        <h1 className="hero-title hero-title-minimal">iceberg-search</h1>
        <QueryInput onSubmit={onSubmit} disabled={sending} />
      </section>
    </div>
  );
}
