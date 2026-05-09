import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const button = cva(
  [
    "inline-flex items-center justify-center gap-1.5 whitespace-nowrap",
    "rounded-md text-sm font-medium tracking-tight",
    "transition-[background-color,color,border-color,transform,box-shadow]",
    "duration-150 ease-spring",
    "active:scale-[0.985] gpu",
    "disabled:pointer-events-none disabled:opacity-50",
  ],
  {
    variants: {
      intent: {
        primary: [
          "bg-accent text-accent-fg shadow-sm",
          "hover:bg-accent/90",
        ],
        secondary: [
          "surface hover:bg-bg-raised",
          "text-fg",
        ],
        ghost: [
          "text-fg-muted hover:text-fg hover:bg-bg-subtle",
        ],
        outline: [
          "border border-border bg-transparent text-fg",
          "hover:border-border-strong hover:bg-bg-subtle",
        ],
        danger: [
          "bg-danger/10 text-danger border border-danger/30",
          "hover:bg-danger/20",
        ],
      },
      size: {
        sm: "h-7 px-2.5 text-[13px]",
        md: "h-9 px-3.5",
        lg: "h-11 px-5 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      intent: "secondary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, intent, size, asChild, ...rest }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp ref={ref} className={cn(button({ intent, size }), className)} {...rest} />
    );
  },
);
Button.displayName = "Button";
