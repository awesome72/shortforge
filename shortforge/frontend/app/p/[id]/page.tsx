import { Suspense } from "react";
import { Workspace } from "@/components/Workspace";

// Next 16: params 같은 런타임 데이터는 Suspense 경계 안에서 읽어야 프리렌더를 막지 않는다.
export default function ProjectPage({ params }: PageProps<"/p/[id]">) {
  return (
    <Suspense fallback={<p className="p-10 text-muted">불러오는 중…</p>}>
      <ProjectWorkspace params={params} />
    </Suspense>
  );
}

async function ProjectWorkspace({ params }: { params: PageProps<"/p/[id]">["params"] }) {
  const { id } = await params;
  return <Workspace id={id} />;
}
