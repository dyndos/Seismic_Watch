"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "./ui";
import type { SeismicMapProps } from "./SeismicMap";

const Inner = dynamic(() => import("./SeismicMap"), {
  ssr: false,
  loading: () => <Skeleton className="h-[520px] w-full" />,
});

export default function Map(props: SeismicMapProps) {
  return <Inner {...props} />;
}
