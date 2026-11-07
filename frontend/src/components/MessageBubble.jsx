import Icon from "./Icon.jsx";
import Markdown from "./Markdown.jsx";

export default function MessageBubble({ message, nested = false }) {
  const isHuman = message.role === "human";
  return (
    <div className={`msg ${isHuman ? "msg-human" : "msg-ai"} ${nested ? "msg-nested" : ""}`}>
      {!isHuman && !nested && (
        <div className="msg-avatar" aria-hidden="true">
          <Icon name="bot" size={16} />
        </div>
      )}
      <div className="msg-bubble">
        {isHuman ? (
          <p className="msg-text">{message.content}</p>
        ) : (
          <Markdown>{message.content}</Markdown>
        )}
        {message.streaming && <span className="cursor" aria-hidden="true" />}
      </div>
    </div>
  );
}
