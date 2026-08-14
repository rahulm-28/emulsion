"use client";

import dynamic from "next/dynamic";
import { User } from "lucide-react";
import { authEnabled } from "@/lib/auth";

const ClerkAccount = dynamic(() => import("./clerk/ClerkAccount"), { ssr: false });

/**
 * The account control, or an honest label saying there are no accounts here.
 *
 * Showing nothing in local mode would leave someone wondering where their account went;
 * one word removes the question.
 */
export function AccountButton() {
  if (!authEnabled) {
    return (
      <span
        className="flex items-center gap-1.5 font-mono text-[10px] text-subtle-foreground"
        title="No accounts in local mode — everything belongs to one implicit user"
      >
        <User className="size-3" />
        local
      </span>
    );
  }
  return <ClerkAccount />;
}
