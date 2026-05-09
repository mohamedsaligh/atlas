import { forwardRef, type HTMLAttributes, type TdHTMLAttributes, type ThHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export const TableRoot = forwardRef<HTMLTableElement, HTMLAttributes<HTMLTableElement>>(
  ({ className, ...rest }, ref) => (
    <table
      ref={ref}
      className={cn("w-full text-sm border-separate border-spacing-0", className)}
      {...rest}
    />
  ),
);
TableRoot.displayName = "TableRoot";

export const THead = forwardRef<HTMLTableSectionElement, HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...rest }, ref) => (
    <thead
      ref={ref}
      className={cn("sticky top-0 z-10 bg-bg-subtle/85 backdrop-blur-sm", className)}
      {...rest}
    />
  ),
);
THead.displayName = "THead";

export const TBody = forwardRef<HTMLTableSectionElement, HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...rest }, ref) => <tbody ref={ref} className={className} {...rest} />,
);
TBody.displayName = "TBody";

export const Tr = forwardRef<HTMLTableRowElement, HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...rest }, ref) => (
    <tr
      ref={ref}
      className={cn(
        "transition-colors duration-150",
        "hover:bg-bg-subtle/60",
        className,
      )}
      {...rest}
    />
  ),
);
Tr.displayName = "Tr";

export const Th = forwardRef<HTMLTableCellElement, ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...rest }, ref) => (
    <th
      ref={ref}
      className={cn(
        "h-10 px-3 text-left text-[11px] font-semibold uppercase tracking-wider",
        "text-fg-subtle border-b border-border",
        className,
      )}
      {...rest}
    />
  ),
);
Th.displayName = "Th";

export const Td = forwardRef<HTMLTableCellElement, TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...rest }, ref) => (
    <td
      ref={ref}
      className={cn("h-10 px-3 align-middle border-b border-border/60", className)}
      {...rest}
    />
  ),
);
Td.displayName = "Td";
