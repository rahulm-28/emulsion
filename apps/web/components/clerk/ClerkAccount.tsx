"use client";

import { UserButton } from "@clerk/nextjs";

export default function ClerkAccount() {
  return <UserButton appearance={{ elements: { avatarBox: "size-6" } }} />;
}
