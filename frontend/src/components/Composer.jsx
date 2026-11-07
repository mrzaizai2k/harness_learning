import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import Icon from "./Icon.jsx";

const Composer = forwardRef(function Composer({ busy, disabled, onSend, onStop, placeholder }, ref) {
  const [value, setValue] = useState("");
  const areaRef = useRef(null);

  useImperativeHandle(ref, () => ({
    fill(text) {
      setValue(text);
      requestAnimationFrame(() => areaRef.current?.focus());
    },
    focus() {
      areaRef.current?.focus();
    },
  }));

  // Auto-grow up to ~8 lines.
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || busy || disabled) return;
    onSend(text);
    setValue("");
  };

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor="composer-input" className="sr-only">
        Message
      </label>
      <textarea
        id="composer-input"
        ref={areaRef}
        rows={1}
        value={value}
        placeholder={placeholder}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        disabled={disabled}
      />
      {busy ? (
        <button type="button" className="btn btn-icon btn-stop" onClick={onStop} title="Stop (Esc)">
          <Icon name="stop" size={16} />
          <span className="sr-only">Stop</span>
        </button>
      ) : (
        <button type="submit" className="btn btn-icon btn-primary" disabled={!value.trim() || disabled} title="Send (Enter)">
          <Icon name="send" size={16} />
          <span className="sr-only">Send</span>
        </button>
      )}
    </form>
  );
});

export default Composer;
