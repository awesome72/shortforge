import { Suspense } from "react";
import { Workspace } from "@/components/Workspace";

// 전문가 화면: 7단계를 하나씩 자세히 다룬다 (쉬운 화면은 /p/[id])
export default function ProWorkspacePage({ params }: PageProps<"/p/[id]/pro">) {
  return (
    <Suspense fallback={<p className="p-10 text-muted">불러오는 중…</p>}>
      <ProWorkspace params={params} />
    </Suspense>
  );
}

async function ProWorkspace({ params }: { params: PageProps<"/p/[id]/pro">["params"] }) {
  const { id } = await params;
  return <Workspace id={id} />;
}
