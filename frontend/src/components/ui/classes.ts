/**
 * Class strings shared by the workspace UI, in the site's existing idiom:
 * square corners, hairline borders, one deep-red accent, visible focus.
 */

export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background";

const buttonBase =
  "inline-flex items-center justify-center gap-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50";

export const buttonPrimary = `${buttonBase} border border-primary bg-primary px-3 py-1.5 font-medium text-primary-foreground hover:bg-primary-hover ${focusRing}`;

export const buttonOutline = `${buttonBase} border border-input bg-background px-3 py-1.5 hover:bg-accent ${focusRing}`;

export const buttonDanger = `${buttonBase} border border-destructive bg-destructive px-3 py-1.5 font-medium text-destructive-foreground hover:bg-destructive/90 ${focusRing}`;

/** Small text-only actions inside rows. */
export const buttonQuiet = `inline-flex items-center gap-1 px-1.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`;

export const buttonQuietDanger = `inline-flex items-center gap-1 px-1.5 py-1 text-xs text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`;

/** Square icon-only button; always pair with an aria-label. */
export const buttonIcon = `inline-flex h-8 w-8 shrink-0 items-center justify-center text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 ${focusRing}`;

export const inputBase =
  "w-full border border-input bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

/** No width of its own: size it where it is used (flex-1, w-16, …). */
export const inputSmall =
  "border border-input bg-background px-2 py-1 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

export const eyebrow = "text-xs font-medium uppercase tracking-wide text-muted-foreground";

export const errorBox = "border border-destructive/30 bg-destructive/5 p-3 text-sm";
