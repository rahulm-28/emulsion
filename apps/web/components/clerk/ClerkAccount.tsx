"use client";

import { UserButton } from "@clerk/nextjs";

/**
 * Profile, password and MFA all live in UserButton's own "Manage account" modal, so
 * there is no separate settings page to build or keep in sync.
 *
 * Where sign-out lands is set once on ClerkProvider — Core 3 dropped the per-button
 * prop.
 */
export default function ClerkAccount() {
  return <UserButton appearance={{ elements: { avatarBox: "size-6" } }} />;
}
