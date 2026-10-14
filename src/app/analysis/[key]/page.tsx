import AnalysisView from "@/components/AnalysisView";

export const dynamic = "force-dynamic";

export default async function AnalysisPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return <AnalysisView eventKey={decodeURIComponent(key)} />;
}
