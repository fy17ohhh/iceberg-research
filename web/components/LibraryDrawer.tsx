"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  deleteDoc,
  getDocPreview,
  listDocs,
  uploadFile,
  type LibraryDoc,
  type LibraryPreview,
} from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

export default function LibraryDrawer() {
  const { locale, t } = useLanguage();
  const [docs, setDocs] = useState<LibraryDoc[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [preview, setPreview] = useState<LibraryPreview | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listDocs().then(setDocs).finally(() => setLoading(false));
  }, []);

  async function openPreview(doc: LibraryDoc) {
    setPreviewing(doc.title);
    setPreviewError("");
    try {
      setPreview(await getDocPreview(doc.title));
    } catch (error) {
      setPreview(null);
      setPreviewError(error instanceof Error ? error.message : String(error));
    } finally {
      setPreviewing(null);
    }
  }

  async function removeDoc(title: string) {
    if (!window.confirm(t("deleteConfirm", { title }))) return;
    await deleteDoc(title);
    setDocs((current) => current.filter((doc) => doc.title !== title));
    if (preview?.title === title) setPreview(null);
  }

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!files?.length) return;
    setUploading(true);
    setUploadError("");
    try {
      for (const file of Array.from(files)) await uploadFile(file);
      setDocs(await listDocs());
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <>
      <button onClick={() => setOpen(true)} className="floating-control library-control" aria-label={t("openLibrary")}>
        <BookIcon />
        <span>{t("library")}</span>
        {docs.length > 0 && <b>{docs.length}</b>}
      </button>

      <div
        className={`fixed inset-0 z-50 bg-[#001f2a]/25 backdrop-blur-sm transition-opacity duration-300 ${open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
        onClick={() => setOpen(false)}
      />

      <aside className={`library-drawer ${open ? "translate-x-0" : "translate-x-full"}`}>
        <header className="flex items-center justify-between border-b border-foreground/10 px-5 py-4">
          <div>
            <p className="ui-eyebrow">{t("knowledgeDock")}</p>
            <h2 className="text-lg font-bold tracking-tight">{t("library")}</h2>
          </div>
          <button onClick={() => setOpen(false)} className="icon-button" aria-label={t("closeLibrary")}><CloseIcon /></button>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(220px,0.82fr)_minmax(0,1.45fr)] max-md:grid-cols-1">
          <div className="thin-scroll overflow-y-auto border-r border-foreground/10 p-3 max-md:border-r-0">
            {loading && <p className="p-3 text-sm text-muted-foreground">{t("loadingLibrary")}</p>}
            {!loading && docs.length === 0 && <p className="p-3 text-sm text-muted-foreground">{t("noDocuments")}</p>}
            <div className="space-y-2">
              {docs.map((doc) => (
                <article
                  key={doc.title}
                  role="button"
                  tabIndex={0}
                  onClick={() => openPreview(doc)}
                  onKeyDown={(event) => { if (event.key === "Enter") openPreview(doc); }}
                  className={`library-item group ${preview?.title === doc.title ? "is-active" : ""}`}
                >
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold">{doc.title}</p>
                    <p className="mt-1 text-[10px] uppercase tracking-[.12em] text-muted-foreground">{formatSourceType(doc.source_type, locale)}</p>
                  </div>
                  <button
                    onClick={(event) => { event.stopPropagation(); void removeDoc(doc.title); }}
                    className="opacity-0 transition-opacity group-hover:opacity-100 text-muted-foreground hover:text-error"
                    aria-label={`${t("deleteDocument")} ${doc.title}`}
                  >
                    <TrashIcon />
                  </button>
                </article>
              ))}
            </div>
          </div>

          <div className="thin-scroll min-h-0 overflow-y-auto bg-white/38 p-6">
            {previewing && <div className="preview-empty"><span className="sonar-loader" />{t("loadingPreview")}</div>}
            {!previewing && previewError && <div className="preview-empty text-error">{previewError}</div>}
            {!previewing && !preview && !previewError && (
              <div className="preview-empty"><BookIcon />{t("selectDocument")}</div>
            )}
            {!previewing && preview && (
              <div>
                <p className="ui-eyebrow">{formatSourceType(preview.source_type, locale)} {t("preview")}</p>
                <h3 className="mb-6 mt-1 text-xl font-bold">{preview.title}</h3>
                <div className="report-prose library-preview">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.content}</ReactMarkdown>
                </div>
              </div>
            )}
          </div>
        </div>

        <footer className="border-t border-foreground/10 p-4">
          {uploadError && (
            <p role="alert" className="mb-3 rounded-xl border border-red-400/25 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-700">
              {uploadError}
            </p>
          )}
          <button onClick={() => fileRef.current?.click()} disabled={uploading} className="upload-button">
            {uploading ? t("uploading") : t("addDocuments")}
          </button>
          <input ref={fileRef} type="file" className="hidden" accept=".pdf,.md,.txt" multiple onChange={handleUpload} />
        </footer>
      </aside>
    </>
  );
}

function formatSourceType(type: string, locale: "en" | "zh-CN") {
  if (type === "arxiv") return "arXiv";
  if (type === "report") return locale === "zh-CN" ? "研究报告" : "Research report";
  if (type === "upload") return locale === "zh-CN" ? "上传文件" : "Upload";
  return type;
}

function BookIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></svg>;
}
function CloseIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}
function TrashIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" /></svg>;
}
