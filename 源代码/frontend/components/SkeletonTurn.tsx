// Skeleton for the in-flight analyze/follow-up. Production rule from
// product.md: skeleton, not spinner-in-content. Three pulsing bars
// approximate the eventual `<h2>` + summary lines + findings list,
// so when the real content lands the layout doesn't jump.

interface SkeletonTurnProps {
  label: string;
}

export function SkeletonTurn({ label }: SkeletonTurnProps) {
  return (
    <article
      role="status"
      aria-live="polite"
      className="flex flex-col gap-4 rounded-[--radius-md] border border-[--color-border] bg-[--color-bg-elev] p-5"
    >
      <div className="flex items-center justify-between">
        <span className="skel h-4 w-44" />
        <span className="skel h-4 w-12" />
      </div>
      <div className="flex flex-col gap-2">
        <span className="skel h-3 w-full" />
        <span className="skel h-3 w-[92%]" />
        <span className="skel h-3 w-[80%]" />
      </div>
      <div className="flex flex-col gap-2 pt-1">
        <span className="skel h-3 w-1/3" />
        <span className="skel h-3 w-[70%]" />
      </div>
      <p className="text-xs text-[--color-fg-faint]">{label}</p>
    </article>
  );
}
