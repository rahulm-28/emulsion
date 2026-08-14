import { SignUp } from "@clerk/nextjs";
import { AuthLayout } from "@/components/AuthLayout";

export default function SignUpPage() {
  return (
    <AuthLayout caption="Create an account to keep your conversations and images">
      <SignUp />
    </AuthLayout>
  );
}
