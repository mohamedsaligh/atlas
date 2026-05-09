import { Link } from "react-router-dom";

export function NotFoundRoute() {
  return (
    <div className="surface rounded-xl px-8 py-16 text-center animate-fade-in">
      <div className="text-5xl font-semibold tracking-tight">404</div>
      <p className="mt-2 text-sm text-fg-muted">No such route.</p>
      <Link to="/" className="mt-4 inline-block text-[13px] text-accent hover:underline">
        Back to home
      </Link>
    </div>
  );
}
