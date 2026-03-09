import { useEffect, useState } from "react";

type Initializer<T> = T | (() => T);

function resolveInitialValue<T>(initialValue: Initializer<T>): T {
  return typeof initialValue === "function" ? (initialValue as () => T)() : initialValue;
}

export function useLocalStorageState<T>(
  key: string,
  initialValue: Initializer<T>,
  options?: {
    serialize?: (value: T) => string;
    deserialize?: (raw: string) => T | null;
  },
) {
  const serialize = options?.serialize ?? JSON.stringify;
  const deserialize = options?.deserialize ?? ((raw: string) => JSON.parse(raw) as T);

  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored == null) {
        return resolveInitialValue(initialValue);
      }
      const parsed = deserialize(stored);
      return parsed == null ? resolveInitialValue(initialValue) : parsed;
    } catch {
      return resolveInitialValue(initialValue);
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, serialize(value));
    } catch {
      return;
    }
  }, [key, serialize, value]);

  return [value, setValue] as const;
}
