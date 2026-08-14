import { SignIn } from "@clerk/nextjs";
import { AuthLayout } from "@/components/AuthLayout";

export default function SignInPage() {
  return (
    <AuthLayout caption="Sign in to keep your conversations and images">
      <SignIn />
    </AuthLayout>
  );
}
