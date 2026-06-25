"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

/** 清理 AI 回复中的文件下载链接文本（文件附件由 page.tsx 通过 SSE 渲染） */
function cleanFileLinks(content: string): string {
  // 移除 "文件已生成！\n[点击下载...](url)\n文件格式: ..." 整段
  let cleaned = content.replace(
    /文件已生成！[\s\S]*?\[点击下载[^\]]*\]\([^)]+\)[\s\S]*?(?:\n|$)/gi,
    ""
  );
  // 移除独立的下载链接行
  cleaned = cleaned.replace(
    /\[(?:点击下载|下载)[^\]]*\]\([^)]+\/files\/[^)]+\)\s*/gi,
    ""
  );
  // 清理多余空行
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n").trim();
  return cleaned;
}

export function MarkdownRenderer({ content }: { content: string }) {
  // 提取图片（AI 生成的图片）
  const images: string[] = [];
  const imgRe = /!\[.*?\]\((https?:\/\/[^\s)]+)\)/gi;
  let m: RegExpExecArray | null;
  while ((m = imgRe.exec(content)) !== null) images.push(m[1]);

  // 清理文件链接文本 + 移除图片 Markdown
  const textOnly = cleanFileLinks(content).replace(/!\[.*?\]\((https?:\/\/[^\s)]+)\)/gi, "");

  const [lightbox, setLightbox] = useState<string | null>(null);
  const [loadedImages, setLoadedImages] = useState<Set<number>>(new Set());

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none [&_pre]:bg-gray-900 [&_pre]:rounded-lg [&_pre]:p-3 [&_pre]:overflow-x-auto [&_code]:text-sm [&_ul]:list-disc [&_ol]:list-decimal [&_blockquote]:border-l-2 [&_blockquote]:border-blue-400 [&_blockquote]:pl-3 [&_blockquote]:text-gray-500 [&_a]:text-blue-500 [&_a]:underline">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{textOnly}</ReactMarkdown>

      {/* AI 生成的图片 */}
      {images.length > 0 && (
        <div className="mt-3 grid gap-3" style={{ gridTemplateColumns: images.length === 1 ? "1fr" : undefined }}>
          {images.map((url, i) => (
            <div key={i} className="relative rounded-xl overflow-hidden bg-gradient-to-br from-indigo-500/10 via-purple-500/10 to-pink-500/10" style={{ maxWidth: images.length === 1 ? "420px" : "300px" }}>
              {!loadedImages.has(i) && (
                <div className="absolute inset-0 flex items-center justify-center" style={{ minHeight: "200px" }}>
                  <div className="flex flex-col items-center gap-2">
                    <div className="text-3xl animate-bounce">🎨</div>
                    <span className="text-xs text-gray-400">加载中...</span>
                  </div>
                </div>
              )}
              <img
                src={url}
                alt="AI 生成的图片"
                className={`w-full rounded-xl cursor-pointer hover:opacity-90 transition-opacity duration-200 ${loadedImages.has(i) ? "opacity-100" : "opacity-0"}`}
                onClick={(e) => { e.stopPropagation(); setLightbox(url); }}
                onLoad={() => setLoadedImages(prev => new Set(prev).add(i))}
              />
            </div>
          ))}
        </div>
      )}

      {/* Lightbox 放大查看 */}
      {lightbox && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={() => setLightbox(null)}>
          <div className="relative max-w-[90vw] max-h-[90vh]">
            <button className="absolute -top-3 -right-3 w-8 h-8 rounded-full bg-white/20 hover:bg-white/30 text-white flex items-center justify-center text-lg cursor-pointer" onClick={() => setLightbox(null)}>✕</button>
            <img src={lightbox} alt="放大查看" className="max-w-full max-h-[85vh] rounded-xl" onClick={(e) => e.stopPropagation()} />
            <a href={lightbox} target="_blank" rel="noopener noreferrer" className="absolute bottom-3 right-3 text-xs text-white/60 hover:text-white bg-black/40 px-2 py-1 rounded-lg" onClick={(e) => e.stopPropagation()}>原图链接 ↗</a>
          </div>
        </div>
      )}
    </div>
  );
}
