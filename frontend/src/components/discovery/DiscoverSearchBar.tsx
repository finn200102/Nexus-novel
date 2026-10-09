import type { FormEvent } from "react";
import { Input } from "../ui";

interface DiscoverSearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** Clear button: defaults to emptying the field. */
  onClear?: () => void;
}

/** Large search field; Enter searches, the clear button resets the query. */
export function DiscoverSearchBar({ value, onChange, onSubmit, onClear }: DiscoverSearchBarProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form className="discover-search" role="search" aria-label="Search the catalog" onSubmit={submit}>
      <Input
        type="search"
        label="Search stories"
        hideLabel
        search
        placeholder="Search by title"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onClear={onClear ?? (() => onChange(""))}
        enterKeyHint="search"
      />
    </form>
  );
}

export default DiscoverSearchBar;
