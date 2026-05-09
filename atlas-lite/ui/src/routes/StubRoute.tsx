import { Construction } from "lucide-react";

export function StubRoute({ title, body }: { title: string; body: string }) {
  return (
    <div className="surface rounded-xl px-8 py-16 text-center animate-fade-in">
      <Construction className="mx-auto h-8 w-8 text-fg-subtle" />
      <h1 className="mt-4 text-lg font-semibold tracking-tight">{title}</h1>
      <p className="mx-auto mt-1 max-w-xl text-sm text-fg-muted">{body}</p>
    </div>
  );
}
