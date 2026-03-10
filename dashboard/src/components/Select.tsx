import { useCallback, useEffect, useRef, useState } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  "aria-label"?: string;
  disabled?: boolean;
}

export function Select({ value, options, onChange, "aria-label": ariaLabel, disabled }: SelectProps) {
  const [open, setOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selected = options.find((o) => o.value === value);

  const close = useCallback(() => {
    setOpen(false);
    setFocusIdx(-1);
  }, []);

  // close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(event: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        close();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open, close]);

  // scroll focused option into view
  useEffect(() => {
    if (!open || focusIdx < 0 || !listRef.current) return;
    const item = listRef.current.children[focusIdx] as HTMLElement | undefined;
    item?.scrollIntoView?.({ block: "nearest" });
  }, [open, focusIdx]);

  function toggle() {
    if (disabled) return;
    if (open) {
      close();
    } else {
      const idx = options.findIndex((o) => o.value === value);
      setFocusIdx(idx >= 0 ? idx : 0);
      setOpen(true);
    }
  }

  function pick(optionValue: string) {
    onChange(optionValue);
    close();
  }

  function handleKeyDown(event: React.KeyboardEvent) {
    if (disabled) return;

    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
      return;
    }

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setFocusIdx((prev) => Math.min(prev + 1, options.length - 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        setFocusIdx((prev) => Math.max(prev - 1, 0));
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        if (focusIdx >= 0 && focusIdx < options.length) {
          pick(options[focusIdx].value);
        }
        break;
      case "Escape":
      case "Tab":
        close();
        break;
    }
  }

  return (
    <div className="select" ref={wrapRef}>
      <button
        className={`select__trigger${open ? " select__trigger--open" : ""}`}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={toggle}
        onKeyDown={handleKeyDown}
      >
        <span className="select__value">{selected?.label ?? value}</span>
        <span className="select__chevron" aria-hidden="true" />
      </button>
      {open ? (
        <div className="select__menu" ref={listRef} role="listbox" aria-label={ariaLabel}>
          {options.map((option, idx) => (
            <div
              key={option.value}
              className={`select__option${option.value === value ? " select__option--selected" : ""}${idx === focusIdx ? " select__option--focused" : ""}`}
              role="option"
              aria-selected={option.value === value}
              onMouseEnter={() => setFocusIdx(idx)}
              onMouseDown={(event) => {
                event.preventDefault();
                pick(option.value);
              }}
            >
              {option.label}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
