import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Report text as rendered markdown; element styles are set here since Tailwind resets them. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="space-y-3 text-[15px] leading-7 text-zinc-800 dark:text-zinc-200 [&_a]:underline [&_code]:rounded [&_code]:bg-zinc-100 [&_code]:px-1 [&_code]:text-sm dark:[&_code]:bg-zinc-800 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_strong]:font-semibold [&_table]:text-sm [&_td]:border-b [&_td]:border-zinc-200 [&_td]:pr-4 dark:[&_td]:border-zinc-800 [&_th]:pr-4 [&_th]:text-left [&_ul]:list-disc">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
