"use client";

import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { startResearch, type ResearchEvent } from "@/lib/api";
import StreamingText from "@/components/StreamingText";

type Verdict = "approved" | "retry" | "replan";

interface SubQuestionInfo {
  label: string;
  question: string;
}

interface CompletedEntry {
  preview: string;
  tool_call_counts: Record<string, number>;
}

interface NavigatorNode {
  kind: "navigator";
  sub_questions: SubQuestionInfo[];
}

interface DiverNode {
  kind: "diver";
  sub_questions: SubQuestionInfo[];
  completed: Map<string, CompletedEntry>;
}

interface SonarNode {
  kind: "sonar";
  round: number;
  results: { question: string; verdict: Verdict; failed: Record<string, boolean>; evidence?: Record<string, string> }[];
  missing_dimensions?: string;
}

interface SynthesizerNode {
  kind: "synthesizer";
  done: boolean;
}

type TimelineNode = NavigatorNode | DiverNode | SonarNode | SynthesizerNode;

export interface ResearchStats {
  total_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export default function ResearchProgress({
  brief,
  onReport,
}: {
  brief: string;
  onReport: (report: string, stats: ResearchStats | null) => void;
}) {
  const [nodes, setNodes] = useState<TimelineNode[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());
  const [expandedSubs, setExpandedSubs] = useState<Set<string>>(new Set());
  const reportRef = useRef<string | null>(null);
  const statsRef = useRef<ResearchStats | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollParentRef = useRef<HTMLElement | null>(null);
  const shouldAutoScrollRef = useRef(true);

  useEffect(() => {
    const abort = startResearch(brief, (event: ResearchEvent) => {
      switch (event.type) {
        case "navigator": {
          const subs = event.sub_questions;
          setNodes((prev) => [...prev, { kind: "navigator", sub_questions: subs }]);
          setTimeout(() => {
            setNodes((prev) => {
              const last = prev[prev.length - 1];
              if (last?.kind === "navigator") {
                return [...prev, { kind: "diver", sub_questions: subs, completed: new Map() }];
              }
              return prev;
            });
          }, 1200);
          break;
        }

        case "diver":
          setNodes((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.kind === "diver") {
              const updated = new Map(last.completed);
              updated.set(event.question, {
                preview: event.preview,
                tool_call_counts: event.tool_call_counts,
              });
              const exists = last.sub_questions.some(
                (sq) => sq.question === event.question
              );
              const questions = exists
                ? last.sub_questions
                : [...last.sub_questions, { label: event.question, question: event.question }];
              next[next.length - 1] = { ...last, sub_questions: questions, completed: updated };
            } else {
              // Late diver event? Find existing diver node, or skip if already past research
              const pastDiver = next.some((n) => n.kind === "sonar" || n.kind === "synthesizer");
              if (pastDiver) {
                // Find the last diver node and update it
                for (let j = next.length - 1; j >= 0; j--) {
                  if (next[j].kind === "diver") {
                    const rn = next[j] as DiverNode;
                    const updated = new Map(rn.completed);
                    updated.set(event.question, {
                      preview: event.preview,
                      tool_call_counts: event.tool_call_counts,
                    });
                    next[j] = { ...rn, completed: updated };
                    break;
                  }
                }
              } else {
                // First diver event: create diver node
                const navigatorNode: NavigatorNode | undefined = [...prev].reverse().find(
                  (n): n is NavigatorNode => n.kind === "navigator"
                );
                const subs = navigatorNode?.sub_questions ?? [];
                const completed = new Map<string, CompletedEntry>();
                completed.set(event.question, {
                  preview: event.preview,
                  tool_call_counts: event.tool_call_counts,
                });
                next.push({ kind: "diver", sub_questions: subs, completed });
              }
            }
            return next;
          });
          break;

        case "sonar": {
          setNodes((prev) => {
            // Skip duplicate review for same round
            if (prev.some((n) => n.kind === "sonar" && (n as SonarNode).round === event.round)) {
              return prev;
            }
            const hasRevise = event.sonar_summary.some((r) => r.verdict === "replan");
            const allApproved = event.sonar_summary.every((r) => r.verdict === "approved");
            const labelMap = new Map<string, string>();
            for (const n of prev) {
              if (n.kind === "navigator") {
                n.sub_questions.forEach((sq) => labelMap.set(sq.question, sq.label));
              }
            }

            const next: TimelineNode[] = [
              ...prev,
              {
                kind: "sonar",
                round: event.round,
                results: event.sonar_summary.map((r) => ({
                  question: r.question,
                  verdict: r.verdict as Verdict,
                  failed: r.failed,
                  evidence: r.evidence,
                })),
                missing_dimensions: event.missing_dimensions,
              },
            ];
            if (allApproved) {
              next.push({ kind: "synthesizer", done: false });
            } else if (!hasRevise) {
              const retryQuestions = event.sonar_summary
                .filter((r) => r.verdict === "retry")
                .map((r) => ({
                  label: labelMap.get(r.question) || r.question,
                  question: r.question,
                }));
              if (retryQuestions.length > 0) {
                next.push({ kind: "diver", sub_questions: retryQuestions, completed: new Map() });
              }
            }
            return next;
          });
          break;
        }

        case "synthesizer":
          reportRef.current = event.report;
          setNodes((prev) => {
            const next = [...prev];
            const synthesizerIdx = next.findIndex((n) => n.kind === "synthesizer");
            if (synthesizerIdx >= 0) {
              next[synthesizerIdx] = { kind: "synthesizer", done: true };
            } else {
              next.push({ kind: "synthesizer", done: true });
            }
            return next;
          });
          break;

        case "stats":
          statsRef.current = {
            total_calls: event.total_calls,
            prompt_tokens: event.prompt_tokens,
            completion_tokens: event.completion_tokens,
            total_tokens: event.total_tokens,
          };
          if (reportRef.current) {
            onReport(reportRef.current, statsRef.current);
          }
          break;

        case "error":
          setError(event.message);
          break;
      }
    });

    return abort;
  }, [brief]);

  useEffect(() => {
    const container = bottomRef.current?.closest("[data-scroll-container]") as HTMLElement | null;
    if (!container) return;
    scrollParentRef.current = container;

    const onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      shouldAutoScrollRef.current = scrollHeight - scrollTop - clientHeight < 80;
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (shouldAutoScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [nodes]);

  // compute "current round" per node kind
  let lastSonarIdx = -1;
  nodes.forEach((n, i) => {
    if (n.kind === "sonar") lastSonarIdx = i;
  });

  // build question → label map from all Navigator nodes (replan adds new entries)
  const questionLabels = new Map<string, string>();
  for (const n of nodes) {
    if (n.kind === "navigator") {
      n.sub_questions.forEach((sq) => questionLabels.set(sq.question, sq.label));
    }
  }

  // check if review is pending (all research done, no review/write yet)
  const lastNode = nodes[nodes.length - 1];
  const showSonarPending =
    lastNode?.kind === "diver" &&
    lastNode.sub_questions.length > 0 &&
    lastNode.completed.size === lastNode.sub_questions.length;

  // research pending: plan is done but no diver node yet
  const showDiverPending = lastNode?.kind === "navigator";

  // replan pending: review has replan items, waiting for new plan
  const showReplanPending =
    lastNode?.kind === "sonar" &&
    lastNode.results.some((r) => r.verdict === "replan");

  function toggleExpand(index: number) {
    const nodeEl = document.querySelector(`[data-node-idx="${index}"]`) as HTMLElement | null;
    const topBefore = nodeEl?.getBoundingClientRect().top ?? 0;

    flushSync(() => {
      setExpandedSet((prev) => {
        const next = new Set(prev);
        if (next.has(index)) next.delete(index);
        else next.add(index);
        return next;
      });
    });

    if (nodeEl) {
      const topAfter = nodeEl.getBoundingClientRect().top;
      const delta = topAfter - topBefore;
      if (Math.abs(delta) > 1) {
        (scrollParentRef.current ?? window).scrollBy(0, delta);
      }
    }
  }

  return (
    <div className="w-full max-w-2xl flex flex-col gap-1.5 bubble-enter">
      {/* AssistantMsg header */}
      <div className="flex items-center gap-1.5 font-mono text-[10px] tracking-widest uppercase text-muted-foreground">
        <span className="w-1.5 h-1.5 rounded-full bg-foreground/70" />
        Assistant
      </div>

      {/* Timeline */}
      <div className="relative pl-7">
        <div className="absolute left-[13px] top-0 bottom-2 w-0.5 bg-foreground/8" />

        {/* Initial loading */}
        {nodes.length === 0 && !error && (
          <div className="relative pb-4 bubble-enter">
            <TimelineDot active />
            <NodeBubble>
              <StreamingText text="正在规划研究方案" mode="dots" />
            </NodeBubble>
          </div>
        )}

        {nodes.map((node, i) => {
          const isLatest = i === nodes.length - 1;
          const isRetry = node.kind === "diver" && nodes.slice(0, i).some((n) => n.kind === "sonar");

          if (node.kind === "synthesizer") {
            return (
              <div key={i} data-node-idx={i} className="relative pb-4 last:pb-0 bubble-enter">
                <TimelineDot active={isLatest} />
                <NodeBubble>
                  <div className="flex items-center gap-1.5">
                    {node.done ? (
                      <StatusLabel dot="bg-approved" text="已完成" color="text-approved" />
                    ) : (
                      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse-dot" />
                    )}
                    <span className="text-[14px] font-medium">{nodeLabel(node)}</span>
                  </div>
                  {!node.done && (
                    <div className="mt-2">
                      <StreamingText text="正在撰写研究报告" mode="dots" />
                    </div>
                  )}
                </NodeBubble>
              </div>
            );
          }

          const autoCollapsed = node.kind === "navigator" && !isLatest;
          const isExpanded = autoCollapsed ? expandedSet.has(i) : !expandedSet.has(i);

          return (
            <div key={i} data-node-idx={i} className="relative pb-4 last:pb-0 bubble-enter">
              <TimelineDot active={isLatest} />

              <NodeBubble>
                {/* Header */}
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => toggleExpand(i)}
                    className="p-1 -ml-1 rounded-md hover:bg-foreground/5 transition-colors"
                  >
                    <svg
                      className={`w-3.5 h-3.5 text-muted-foreground transition-transform duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] ${
                        isExpanded ? "rotate-90" : ""
                      }`}
                      viewBox="0 0 12 12"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    >
                      <path d="M4.5 2.5l4 3.5-4 3.5" />
                    </svg>
                  </button>
                  <span className="text-[14px] font-medium">{nodeLabel(node, isRetry)}</span>
                  {!isExpanded && (
                    <span className="text-[12px] text-muted-foreground/60 ml-0.5">
                      {nodeSummary(node)}
                    </span>
                  )}
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateRows: isExpanded ? "1fr" : "0fr",
                    opacity: isExpanded ? 1 : 0,
                    transition: isExpanded
                      ? "grid-template-rows 0.5s cubic-bezier(0.2,0.8,0.2,1), opacity 0.4s ease 0.08s"
                      : "grid-template-rows 0.5s cubic-bezier(0.2,0.8,0.2,1) 0.05s, opacity 0.25s ease",
                  }}
                >
                  <div style={{ overflow: "hidden" }}>
                    <div className="mt-2.5">
                      <NodeContent
                        node={node}
                        index={i}
                        isCurrentRound={
                          node.kind === "diver"
                            ? !nodes.slice(i + 1).some((n) => n.kind === "sonar" || n.kind === "synthesizer")
                            : node.kind === "sonar" && i === lastSonarIdx
                        }
                        questionLabels={questionLabels}
                        expandedSubs={expandedSubs}
                        toggleSub={(key) =>
                          setExpandedSubs((prev) => {
                            const next = new Set(prev);
                            if (next.has(key)) next.delete(key);
                            else next.add(key);
                            return next;
                          })
                        }
                      />
                    </div>
                  </div>
                </div>
              </NodeBubble>
            </div>
          );
        })}

        {/* Research pending — plan done, waiting for first diver event */}
        {showDiverPending && (
          <div className="relative pb-4 bubble-enter">
            <TimelineDot active />
            <NodeBubble>
              <StreamingText text="正在启动研究" mode="dots" />
            </NodeBubble>
          </div>
        )}

        {/* Review pending — sub-question list with shimmer */}
        {showSonarPending && lastNode?.kind === "diver" && (
          <div className="relative pb-4 bubble-enter">
            <TimelineDot active />
            <NodeBubble>
              <div className="flex items-center gap-1.5">
                <span className="text-[14px] font-medium inline-flex items-center gap-2">
                  审查中
                  <span className="dots-pulse"><i /><i /><i /></span>
                </span>
              </div>
              <div className="mt-2.5">
                <ul className="space-y-3">
                  {lastNode.sub_questions.map((sq, i) => (
                    <li key={i}>
                      <div className="flex items-center gap-1.5">
                        <StatusLabel
                          dot="bg-blue animate-pulse-dot"
                          text="审查中"
                          color="text-blue"
                        />
                        <span className="text-[14px] font-medium">
                          {questionLabels.get(sq.question) || sq.label}
                        </span>
                      </div>
                      <p className="mt-1 ml-5 shimmer-text text-[13px]">
                        正在审查研究质量
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            </NodeBubble>
          </div>
        )}

        {/* Replan pending indicator — review requested replanning */}
        {showReplanPending && (
          <div className="relative pb-4 bubble-enter">
            <TimelineDot active />
            <NodeBubble>
              <StreamingText text="正在重新规划研究方案" mode="dots" />
            </NodeBubble>
          </div>
        )}

        {error && (
          <div className="relative pb-4 bubble-enter">
            <TimelineDot error />
            <NodeBubble>
              <p className="text-[14px] text-error break-all leading-relaxed">{error}</p>
            </NodeBubble>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function TimelineDot({ active, error: isError }: { active?: boolean; error?: boolean }) {
  return (
    <div
      className={`absolute -left-[19px] top-[14px] w-2.5 h-2.5 rounded-full border-[1.5px] transition-colors duration-300 ${
        isError
          ? "border-error bg-error/20"
          : active
            ? "border-accent bg-accent/20"
            : "border-foreground/20 bg-surface"
      }`}
    />
  );
}

function NodeBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl rounded-bl-sm bg-surface/80 px-4 py-3 shadow-[0_1px_4px_rgba(0,0,0,0.04)] overflow-hidden">
      {children}
    </div>
  );
}

function nodeLabel(node: TimelineNode, isRetry = false): React.ReactNode {
  switch (node.kind) {
    case "navigator":
      return `共分解出 ${node.sub_questions.length} 个子问题`;
    case "diver": {
      const total = node.sub_questions.length;
      const done = node.completed.size;
      const phase = isRetry ? "补充研究" : "资料收集";
      if (done === 0) {
        return (
          <span className="inline-flex items-center gap-2">
            {phase}
            <span className="dots-pulse"><i /><i /><i /></span>
          </span>
        );
      }
      if (done < total) {
        return (
          <span className="inline-flex items-center gap-2">
            {phase}（{done}/{total}）
            <span className="dots-pulse"><i /><i /><i /></span>
          </span>
        );
      }
      return `${phase}完成（${total}/${total}）`;
    }
    case "sonar":
      return `审查 · 第 ${node.round} 轮`;
    case "synthesizer":
      return node.done ? "报告已生成" : "生成报告";
  }
}

function nodeSummary(node: TimelineNode): string {
  switch (node.kind) {
    case "navigator":
      return `${node.sub_questions.length} 个子问题`;
    case "diver":
      return `${node.completed.size}/${node.sub_questions.length} 完成`;
    case "sonar": {
      const approved = node.results.filter((r) => r.verdict === "approved").length;
      if (approved === node.results.length) return "全部通过";
      return `${approved}/${node.results.length} 通过`;
    }
    case "synthesizer":
      return node.done ? "已完成" : "进行中";
  }
}

function truncate(text: string, max = 60): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "...";
}

function NodeContent({
  node,
  index,
  isCurrentRound,
  questionLabels,
  expandedSubs,
  toggleSub,
}: {
  node: TimelineNode;
  index: number;
  isCurrentRound: boolean;
  questionLabels: Map<string, string>;
  expandedSubs: Set<string>;
  toggleSub: (key: string) => void;
}) {
  switch (node.kind) {
    case "navigator":
      return (
        <ul className="space-y-2.5">
          {node.sub_questions.map((sq, i) => (
            <li key={i} className="flex items-start gap-2 text-[14px] leading-snug">
              <span className="text-muted-foreground font-mono text-[13px] mt-px">{i + 1}.</span>
              <div>
                <span className="font-medium">{sq.label}</span>
                <span className="text-foreground/50 block text-[13px]">{truncate(sq.question, 80)}</span>
              </div>
            </li>
          ))}
        </ul>
      );

    case "diver": {
      return (
        <ul className="space-y-3">
          {node.sub_questions.map((sq, i) => {
            const entry = node.completed.get(sq.question);
            const isDone = entry !== undefined;
            const toolUsage = entry ? formatToolUsage(entry.tool_call_counts) : null;
            const subKey = `${index}-${i}`;
            // current round: expanded unless explicitly collapsed
            // old round: collapsed unless explicitly expanded
            const isExpanded = isCurrentRound
              ? !expandedSubs.has(subKey)
              : expandedSubs.has(subKey);

            return (
              <li key={i}>
                <button
                  onClick={() => toggleSub(subKey)}
                  className="flex items-center gap-1.5 w-full text-left hover:opacity-70 transition-opacity"
                >
                  <svg
                    className={`w-3 h-3 text-muted-foreground shrink-0 transition-transform duration-[0.35s] ease-[cubic-bezier(0.2,0.8,0.2,1)] ${
                      isExpanded ? "rotate-90" : ""
                    }`}
                    viewBox="0 0 12 12"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  >
                    <path d="M5 2.5l3 3.5-3 3.5" />
                  </svg>
                  <StatusLabel
                    dot={isDone ? "bg-approved" : "bg-accent animate-pulse-dot"}
                    text={isDone ? "已完成" : "研究中"}
                    color={isDone ? "text-approved" : "text-accent"}
                  />
                  <span className="text-[14px] font-medium">{sq.label}</span>
                </button>

                {isExpanded && (
                  <div className="mt-1.5 ml-5 space-y-1">
                    <p className={`text-[13px] leading-snug ${!isDone ? "shimmer-text" : "text-foreground/50"}`}>
                      {truncate(sq.question, 85)}
                    </p>
                    {isDone && toolUsage && (
                      <p className="text-[13px] text-foreground/30">
                        {toolUsage}
                      </p>
                    )}
                    {isDone && entry.preview && (
                      <p className="text-[13px] text-foreground/30 leading-relaxed line-clamp-2">
                        {entry.preview}
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      );
    }

    case "sonar": {
      return (
        <div>
          <ul className="space-y-3">
            {node.results.map((r, i) => {
              const subKey = `${index}-${i}`;
              const isExpanded = isCurrentRound
                ? !expandedSubs.has(subKey)
                : expandedSubs.has(subKey);
              const label = questionLabels.get(r.question) || truncate(r.question, 20);
              return (
                <li key={i}>
                  <button
                    onClick={() => toggleSub(subKey)}
                    className="flex items-center gap-1.5 w-full text-left hover:opacity-70 transition-opacity"
                  >
                    <svg
                      className={`w-3 h-3 text-muted-foreground shrink-0 transition-transform duration-[0.35s] ease-[cubic-bezier(0.2,0.8,0.2,1)] ${
                        isExpanded ? "rotate-90" : ""
                      }`}
                      viewBox="0 0 12 12"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    >
                      <path d="M5 2.5l3 3.5-3 3.5" />
                    </svg>
                    <VerdictLabel verdict={r.verdict} failed={r.failed} />
                    <span className="text-[14px] font-medium">{label}</span>
                  </button>
                  {isExpanded && (
                    <div className="mt-1.5 ml-5">
                      <CriteriaRow failed={r.failed} evidence={r.evidence} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {node.missing_dimensions && (
            <div className="mt-3 pt-2.5 border-t border-foreground/8">
              <p className="text-[12px] text-retry leading-snug">
                <span className="font-medium">缺失维度</span>
                <span className="mx-1">·</span>
                {node.missing_dimensions}
              </p>
            </div>
          )}
        </div>
      );
    }

    case "synthesizer":
      return node.done ? null : <StreamingText text="正在撰写研究报告" mode="dots" />;
  }
}

function StatusLabel({ dot, text, color }: { dot: string; text: string; color: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-[13px] ${color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
      {text}
    </span>
  );
}

function VerdictLabel({ verdict, failed }: { verdict: Verdict; failed?: Record<string, boolean> }) {
  const config = {
    approved: { dot: "bg-approved", text: "通过", color: "text-approved" },
    retry: { dot: "bg-retry animate-pulse-dot", text: "重试", color: "text-retry" },
    replan: { dot: "bg-error", text: "重规划", color: "text-error" },
  };
  const c = config[verdict];
  let label = c.text;
  if (verdict !== "approved" && failed) {
    const failedNames = Object.entries(failed)
      .filter(([, v]) => v)
      .map(([k]) => CRITERIA_LABELS[k] || k);
    if (failedNames.length > 0) {
      label += ` · ${failedNames.join("、")}`;
    }
  }
  return <StatusLabel dot={c.dot} text={label} color={c.color} />;
}

const CRITERIA_LABELS: Record<string, string> = {
  relevance: "相关性",
  depth: "深度",
  citations: "引用",
  sources: "来源",
  completeness: "完整性",
};

function CriteriaRow({ failed, evidence }: { failed: Record<string, boolean>; evidence?: Record<string, string> }) {
  const entries = Object.entries(CRITERIA_LABELS);
  const failedEntries = entries.filter(([key]) => failed[key]);
  const passedEntries = entries.filter(([key]) => !failed[key]);

  return (
    <div>
      {failedEntries.length > 0 && (
        <div className="space-y-1">
          {failedEntries.map(([key, label]) => (
            <div key={key} className="flex items-start gap-1.5 text-[13px] leading-snug">
              <span className="text-error shrink-0">✗</span>
              <div>
                <span className="font-medium text-error">{label}</span>
                {evidence?.[key] && (
                  <span className="ml-1.5 text-foreground/50">{truncate(evidence[key], 80)}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {passedEntries.length > 0 && (
        <div className={`flex items-center gap-x-2 flex-wrap text-[12px] text-foreground/30 ${failedEntries.length > 0 ? "mt-1.5" : ""}`}>
          {passedEntries.map(([key, label]) => (
            <span key={key} className="inline-flex items-center gap-0.5">✓ {label}</span>
          ))}
        </div>
      )}
    </div>
  );
}

const TOOL_NAMES: Record<string, string> = {
  "mcp__brave-search__brave_web_search": "Brave 搜索",
  "mcp__tavily__tavily_search": "Tavily 搜索",
  "mcp__fetch__fetch": "抓取网页",
  "mcp__paper-search__search_arxiv": "arXiv 搜索",
  "mcp__paper-search__search_google_scholar": "Google Scholar",
  "mcp__paper-search__download_arxiv": "下载论文",
  "mcp__paper-search__read_arxiv_paper": "读取论文",
  "mcp__pdf-reader__read_pdf": "PDF 读取与证据提取",
  "mcp__pdf-reader__search_pdf": "PDF 内容检索",
  "mcp__pdf-reader__pdf_evidence": "PDF 页面证据",
  "mcp__github__search_repositories": "GitHub 搜索",
  "mcp__github__get_file_contents": "GitHub 文件",
  "mcp__github__search_code": "GitHub 代码",
  "search": "搜索",
  "read_arxiv_paper": "论文阅读",
  "rag_search": "本地知识库",
};

function formatToolUsage(tool_call_counts: Record<string, number>): string | null {
  const parts = Object.entries(tool_call_counts)
    .filter(([, count]) => count > 0)
    .map(([name, count]) => {
      const label = TOOL_NAMES[name] || name;
      return count > 1 ? `${label} ×${count}` : label;
    });
  if (parts.length === 0) return null;
  return "调用了 " + parts.join("、");
}
