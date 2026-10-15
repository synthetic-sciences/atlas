import { mkdirSync, writeFileSync } from "node:fs";

const token = process.env.VERCEL_TOKEN;
if (!token) throw new Error("A Vercel deployment credential is required");
const team = process.env.VERCEL_TEAM_ID || process.env.VERCEL_ORG_ID;
const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

async function request(path) {
  const url = new URL(path, "https://api.vercel.com");
  if (team) url.searchParams.set("teamId", team);
  const response = await fetch(url, { headers, signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw new Error(`Vercel ${url.pathname} returned HTTP ${response.status}`);
  return response.json();
}

const listed = await request("/v9/projects?limit=100");
const candidates = listed.projects.filter(project =>
  [1244965779, 1420201479].includes(Number(project.link?.repoId)) || /atlas|tryatlas/i.test(project.name),
);
const projects = [];
for (const project of candidates) {
  const domains = await request(`/v9/projects/${project.id}/domains`);
  projects.push({ id: project.id, name: project.name, accountId: project.accountId, rootDirectory: project.rootDirectory, link: project.link, domains: domains.domains.map(domain => domain.name), buildCommand: project.buildCommand, installCommand: project.installCommand, outputDirectory: project.outputDirectory });
}
mkdirSync("dist/deployments", { recursive: true });
writeFileSync("dist/deployments/landing-project.json", `${JSON.stringify({ projects }, null, 2)}\n`);
console.log(JSON.stringify({ projects }, null, 2));
const target = projects.filter(project => project.domains.includes("tryatlas.sh"));
if (target.length !== 1) throw new Error("Expected exactly one existing project owning tryatlas.sh");
