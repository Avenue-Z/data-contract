import { greet } from "@/lib/greet";

export default function Page() {
  return <main>{greet("world")}</main>;
}
