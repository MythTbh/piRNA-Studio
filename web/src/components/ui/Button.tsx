import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

// Composable shadcn/ui Button pattern using the workspace design tokens.
const variants = cva(
  "inline-flex items-center justify-center gap-2 font-medium disabled:opacity-50 focus-visible:outline-offset-2",
  {
    variants: {
      variant: { default: "primary", outline: "btn", icon: "theme" },
    },
    defaultVariants: { variant: "outline" },
  },
);
interface Props
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof variants> {
  asChild?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant, className, asChild = false, ...props }, ref) => {
    const Component = asChild ? Slot : "button";
    return (
      <Component
        ref={ref}
        className={variants({ variant, className })}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
