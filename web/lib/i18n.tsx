"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export type AppLocale = "en" | "zh-CN";

const messages = {
  en: {
    language: "Language",
    english: "English",
    chinese: "简体中文",
    researchQuestionPlaceholder: "Ask a research question…",
    submitResearch: "Start research",
    library: "Library",
    knowledgeDock: "Knowledge dock",
    openLibrary: "Open library",
    closeLibrary: "Close library",
    loadingLibrary: "Loading library…",
    noDocuments: "No documents yet.",
    loadingPreview: "Loading preview…",
    selectDocument: "Select a document to preview",
    preview: "preview",
    deleteDocument: "Delete",
    deleteConfirm: "Delete “{title}”?",
    uploading: "Uploading…",
    addDocuments: "+ Add PDF, Markdown or Text",
    upload: "Upload",
    report: "Research report",
    preferences: "Preferences",
    longTermPreferences: "Long-term research preferences",
    preferencesDescription: "Saved preferences are recalled for relevant research, so you do not need to repeat them.",
    close: "Close",
    loadingMemory: "Loading preferences…",
    reportStyle: "Report style",
    reportLanguage: "Report language",
    followQuestionLanguage: "Follow question language",
    chineseLanguage: "Chinese",
    analysisDepth: "Analysis depth",
    concise: "Concise",
    balanced: "Balanced",
    deep: "Deep",
    sourceStrategy: "Source strategy",
    preferPrimary: "Prefer primary sources",
    primaryDescription: "Official documents, original reports, and datasets",
    preferAcademic: "Prefer academic sources",
    academicDescription: "Papers, conferences, and academic material",
    includeCode: "Find code implementations",
    codeDescription: "Add official repositories or high-quality implementations when relevant",
    evidenceDetail: "Evidence and detail",
    includeMethodology: "Include methodology",
    methodologyDescription: "Mechanisms, experimental design, and key steps",
    includeQuantitative: "Include quantitative evidence",
    quantitativeDescription: "Metrics, data, dates, and experimental results",
    researchBackground: "Long-term research context",
    contextDescription: "Add your goals, research interests, or background. Do not include API keys, passwords, or other credentials.",
    contextPlaceholder: "For example: I am building an Iceberg Research Agent and preparing for agent-algorithm roles. Focus on method design, evaluation, and reliability.",
    memoryDescription: "Completed research extracts a small set of sourced atomic facts. Only facts relevant to the current question are recalled; full history is never placed in context.",
    savingPreferences: "Saving preferences…",
    preferencesSaved: "Saved",
    savePreferences: "Save preferences",
    returnToSurface: "Return to surface",
    exitResearch: "Exit current research?",
    exitDescription: "Returning to the surface will stop the current research and clear generated content. You can continue or exit now.",
    continueResearch: "Continue research",
    confirmExit: "Exit research",
    analyzingQuestion: "Analyzing your question",
    analysisFailed: "Could not analyze this question: {detail}",
    refiningPlan: "Got it — refining the research plan…",
    refineFailed: "Could not refine the research plan: {detail}",
    directionPlaceholder: "Or enter a specific direction…",
    clarifyPlaceholder: "Enter the full term, domain, or research goal…",
    researchConfirmed: "Research direction confirmed. Starting research:",
    assistant: "Assistant",
    saved: "Saved",
    saving: "Saving…",
    saveToLibrary: "Save to library",
    printPdf: "Print PDF",
    planning: "Planning the research",
    completed: "Completed",
    writingReport: "Writing the research report",
    startingResearch: "Starting research",
    reviewing: "Reviewing",
    reviewingQuality: "Reviewing research quality",
    replanning: "Replanning the research",
    subQuestions: "{count} sub-questions mapped",
    supplementaryResearch: "Supplementary research",
    evidenceCollection: "Evidence collection",
    phaseProgress: "{phase} ({done}/{total})",
    phaseCompleted: "{phase} complete ({total}/{total})",
    reviewRound: "Review · round {round}",
    reportReady: "Report ready",
    generateReport: "Generate report",
    subQuestionCount: "{count} sub-questions",
    completeProgress: "{done}/{total} complete",
    allApproved: "All approved",
    approvedProgress: "{done}/{total} approved",
    inProgress: "In progress",
    researching: "Researching",
    missingDimensions: "Missing dimensions",
    approved: "Approved",
    retry: "Retry",
    replan: "Replan",
    relevance: "Relevance",
    depth: "Depth",
    citations: "Citations",
    sources: "Sources",
    completeness: "Completeness",
    toolUsage: "Used {tools}",
    toolBrave: "Brave search",
    toolTavily: "Tavily search",
    toolFetch: "Web fetch",
    toolArxivSearch: "arXiv search",
    toolGoogleScholar: "Google Scholar",
    toolPaperDownload: "Paper download",
    toolPaperRead: "Paper reading",
    toolPdfRead: "PDF reading & evidence extraction",
    toolPdfSearch: "PDF search",
    toolPdfEvidence: "PDF page evidence",
    toolGithubSearch: "GitHub search",
    toolGithubFile: "GitHub file",
    toolGithubCode: "GitHub code",
    toolSearch: "Search",
    toolRag: "Local knowledge base",
  },
  "zh-CN": {
    language: "语言",
    english: "English",
    chinese: "简体中文",
    researchQuestionPlaceholder: "输入研究问题…",
    submitResearch: "开始研究",
    library: "文档库",
    knowledgeDock: "知识库",
    openLibrary: "打开文档库",
    closeLibrary: "关闭文档库",
    loadingLibrary: "正在读取文档库…",
    noDocuments: "暂时没有文档。",
    loadingPreview: "正在加载预览…",
    selectDocument: "选择一个文档进行预览",
    preview: "预览",
    deleteDocument: "删除",
    deleteConfirm: "删除“{title}”？",
    uploading: "正在上传…",
    addDocuments: "+ 添加 PDF、Markdown 或文本",
    upload: "上传",
    report: "研究报告",
    preferences: "偏好",
    longTermPreferences: "长期研究偏好",
    preferencesDescription: "保存后会在相关研究中自动召回，无需重复说明。",
    close: "关闭",
    loadingMemory: "正在读取偏好…",
    reportStyle: "报告形式",
    reportLanguage: "报告语言",
    followQuestionLanguage: "跟随问题语言",
    chineseLanguage: "中文",
    analysisDepth: "分析深度",
    concise: "简洁",
    balanced: "平衡",
    deep: "深入",
    sourceStrategy: "来源策略",
    preferPrimary: "优先一手来源",
    primaryDescription: "官方文档、原始报告和数据集",
    preferAcademic: "优先学术来源",
    academicDescription: "论文、会议和学术资料",
    includeCode: "寻找代码实现",
    codeDescription: "相关时补充官方仓库或高质量实现",
    evidenceDetail: "证据与细节",
    includeMethodology: "包含方法细节",
    methodologyDescription: "机制、实验设计和关键步骤",
    includeQuantitative: "包含量化证据",
    quantitativeDescription: "指标、数据、日期和实验结果",
    researchBackground: "长期研究背景",
    contextDescription: "填写长期目标、研究方向或知识背景。不要填写 API Key、密码等凭证。",
    contextPlaceholder: "例如：我正在研究 Iceberg Research Agent，并准备 Agent 算法岗位，希望重点关注方法设计、评测和可靠性。",
    memoryDescription: "完成的研究会自动提取少量、带来源的原子事实。系统只按当前问题召回相关记忆，不会把全部历史塞进上下文。",
    savingPreferences: "正在保存偏好…",
    preferencesSaved: "已保存",
    savePreferences: "保存研究偏好",
    returnToSurface: "返回水面",
    exitResearch: "退出当前搜索？",
    exitDescription: "返回水面会终止当前搜索进度，并清除所有已生成的内容。你可以选择继续搜索或退出。",
    continueResearch: "继续搜索",
    confirmExit: "确认退出",
    analyzingQuestion: "正在分析问题",
    analysisFailed: "暂时无法完成问题分析：{detail}",
    refiningPlan: "收到，正在整理研究方案…",
    refineFailed: "暂时无法整理研究方案：{detail}",
    directionPlaceholder: "或者输入你的具体方向…",
    clarifyPlaceholder: "输入全称、所属领域或研究目标…",
    researchConfirmed: "好的，研究方向已确认，即将开始研究：",
    assistant: "助手",
    saved: "已保存",
    saving: "保存中…",
    saveToLibrary: "保存到文献库",
    printPdf: "打印 PDF",
    planning: "正在规划研究方案",
    completed: "已完成",
    writingReport: "正在撰写研究报告",
    startingResearch: "正在启动研究",
    reviewing: "审查中",
    reviewingQuality: "正在审查研究质量",
    replanning: "正在重新规划研究方案",
    subQuestions: "共分解出 {count} 个子问题",
    supplementaryResearch: "补充研究",
    evidenceCollection: "资料收集",
    phaseProgress: "{phase}（{done}/{total}）",
    phaseCompleted: "{phase}完成（{total}/{total}）",
    reviewRound: "审查 · 第 {round} 轮",
    reportReady: "报告已生成",
    generateReport: "生成报告",
    subQuestionCount: "{count} 个子问题",
    completeProgress: "{done}/{total} 完成",
    allApproved: "全部通过",
    approvedProgress: "{done}/{total} 通过",
    inProgress: "进行中",
    researching: "研究中",
    missingDimensions: "缺失维度",
    approved: "通过",
    retry: "重试",
    replan: "重规划",
    relevance: "相关性",
    depth: "深度",
    citations: "引用",
    sources: "来源",
    completeness: "完整性",
    toolUsage: "调用了 {tools}",
    toolBrave: "Brave 搜索",
    toolTavily: "Tavily 搜索",
    toolFetch: "抓取网页",
    toolArxivSearch: "arXiv 搜索",
    toolGoogleScholar: "Google Scholar 搜索",
    toolPaperDownload: "下载论文",
    toolPaperRead: "读取论文",
    toolPdfRead: "PDF 读取与证据提取",
    toolPdfSearch: "PDF 内容检索",
    toolPdfEvidence: "PDF 页面证据",
    toolGithubSearch: "GitHub 搜索",
    toolGithubFile: "GitHub 文件",
    toolGithubCode: "GitHub 代码",
    toolSearch: "搜索",
    toolRag: "本地知识库",
  },
} as const;

export type TranslationKey = keyof typeof messages.en;
export type Translate = (key: TranslationKey, variables?: Record<string, string | number>) => string;

const LanguageContext = createContext<{
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
  t: Translate;
} | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<AppLocale>("en");

  useEffect(() => {
    const saved = window.localStorage.getItem("iceberg-research-locale");
    if (saved === "en" || saved === "zh-CN") setLocale(saved);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("iceberg-research-locale", locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => ({
    locale,
    setLocale,
    t: (key: TranslationKey, variables: Record<string, string | number> = {}) => {
      const template: string = messages[locale][key];
      return Object.entries(variables).reduce<string>(
        (text, [name, replacement]) => text.replaceAll(`{${name}}`, String(replacement)),
        template,
      );
    },
  }), [locale]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (!context) throw new Error("useLanguage must be used inside LanguageProvider");
  return context;
}

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useLanguage();
  return (
    <div className="fixed bottom-5 left-5 z-[70] inline-flex rounded-full border border-white/20 bg-slate-950/35 p-1 text-xs text-white/75 shadow-lg backdrop-blur-xl">
      <span className="sr-only">{t("language")}</span>
      <button
        type="button"
        aria-pressed={locale === "en"}
        onClick={() => setLocale("en")}
        className={`rounded-full px-3 py-1.5 transition ${locale === "en" ? "bg-white/20 text-white" : "hover:bg-white/10"}`}
      >
        {t("english")}
      </button>
      <button
        type="button"
        aria-pressed={locale === "zh-CN"}
        onClick={() => setLocale("zh-CN")}
        className={`rounded-full px-3 py-1.5 transition ${locale === "zh-CN" ? "bg-white/20 text-white" : "hover:bg-white/10"}`}
      >
        {t("chinese")}
      </button>
    </div>
  );
}
