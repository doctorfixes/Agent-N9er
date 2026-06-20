"use client";import useSWR from"swr";export default function P(){const{data}=useSWR("/api/agents",u=>fetch(u).then(r=>r.json()));return<div>{JSON.stringify(data)}</div>}
