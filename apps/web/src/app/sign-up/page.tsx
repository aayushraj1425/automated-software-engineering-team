import { SignUpForm } from "@/components/auth/sign-up-form";
import { configuredProviders } from "@/lib/sign-in-providers";

// Server component: reads which OAuth providers have credentials and hands
// the client form a plain list — names only, never secrets.
export default function SignUpPage() {
  return <SignUpForm providers={configuredProviders()} />;
}
