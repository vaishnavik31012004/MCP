import { useState } from "react";

export default function GoalForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (goal: string) => void;
  disabled: boolean;
}) {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  }

  return (
    <form className="goal-form" onSubmit={handleSubmit}>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="e.g. Check tomorrow's weather in Mumbai and email me a summary"
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || !value.trim()}>
        Run
      </button>
    </form>
  );
}
