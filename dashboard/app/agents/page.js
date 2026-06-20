"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

export default function AgentsPage() {
  const { data } = useSWR("/api/agents", fetcher);
  return <pre>{JSON.stringify(data ?? {}, null, 2)}</pre>;
}
