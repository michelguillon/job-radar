import * as React from "react";
import { cn } from "@/lib/utils";

// shadcn-style table primitives — plain <table> elements styled with Tailwind. The class is
// never a bare Tailwind utility name, so it can't collide with a utility (the `.grid` bug).
// `table-fixed` + a <colgroup> in the consumer pin column widths so headers stay over columns.

export const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <table ref={ref} className={cn("w-full table-fixed border-collapse bg-panel text-[13px]", className)} {...props} />
  ),
);
Table.displayName = "Table";

export const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => <thead ref={ref} className={cn(className)} {...props} />,
);
TableHeader.displayName = "TableHeader";

export const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => <tbody ref={ref} className={cn(className)} {...props} />,
);
TableBody.displayName = "TableBody";

export const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr ref={ref} className={cn("border-b border-line-soft", className)} {...props} />
  ),
);
TableRow.displayName = "TableRow";

export const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "sticky top-0 z-10 border-b border-line bg-[#fbfbfd] px-[11px] py-[9px] text-left align-middle",
      "text-[11px] font-bold uppercase tracking-wide text-ink-soft whitespace-nowrap",
      className,
    )}
    {...props}
  />
));
TableHead.displayName = "TableHead";

export const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td ref={ref} className={cn("overflow-hidden text-ellipsis px-[11px] py-[9px] align-top", className)} {...props} />
));
TableCell.displayName = "TableCell";
