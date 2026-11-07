import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const components = {
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
};

function Markdown({ children, className = "" }) {
  return (
    <div className={`markdown ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children || ""}
      </ReactMarkdown>
    </div>
  );
}

export default memo(Markdown);
