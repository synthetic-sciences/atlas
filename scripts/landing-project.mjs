import { mkdirSync, writeFileSync } from "node:fs";

const token = process.env.VERCEL_TOKEN;
if (!token) throw new Error("A Vercel deployment credential is required");
const team = process.env.VERCEL_TEAM_ID || process.env.VERCEL_ORG_ID;
const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

async function request(path, method = "GET", body) {
  const url = new URL(path, "https://api.vercel.com");
  if (team) url.searchParams.set("teamId", team);
  const response = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(20000) });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    const message = String(failure.error?.message || failure.error?.code || "Request failed").replaceAll(token, "[redacted]").slice(0, 300);
    throw new Error(`Vercel ${url.pathname} returned HTTP ${response.status}: ${message}`);
  }
  if (response.status === 204) return undefined;
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
const project = target[0];
if (project.id !== "prj_nmItmZ5aP7HOYiS8DLioj0ZzSj2O") throw new Error("Landing project identity changed");
const action = process.env.LANDING_ACTION || "inspect";
if (!["inspect", "migrate", "preview", "production", "rollback"].includes(action)) throw new Error("Unknown landing action");
const endpoint = `/v9/projects/${project.id}`;
const repository = "synthetic-sciences/atlas";

if (action === "migrate" || action === "rollback") {
  const rollback = action === "rollback";
  const repo = rollback ? "synthetic-sciences/atlas-landing" : repository;
  const id = rollback ? 1244965779 : 1420201479;
  if (![1244965779, 1420201479].includes(Number(project.link?.repoId))) throw new Error("Refusing to replace an unexpected Git connection");
  writeFileSync("dist/deployments/landing-before.json", `${JSON.stringify(project, null, 2)}\n`);
  const restore = async () => {
    const current = await request(endpoint);
    if (current.link) await request(`${endpoint}/link`, "DELETE");
    await request(`${endpoint}/link`, "POST", { type: "github", repo: `${project.link.org}/${project.link.repo}` });
    await request(endpoint, "PATCH", { rootDirectory: project.rootDirectory });
  };
  try {
    if (Number(project.link.repoId) !== id) {
      await request(`${endpoint}/link`, "DELETE");
      await request(`${endpoint}/link`, "POST", { type: "github", repo });
    }
    await request(endpoint, "PATCH", { rootDirectory: rollback ? null : "landing" });
    const updated = await request(endpoint);
    if (Number(updated.link?.repoId) !== id || updated.rootDirectory !== (rollback ? null : "landing")) throw new Error("Vercel connection verification failed");
    console.log(JSON.stringify({ project: updated.id, repository: updated.link.repo, rootDirectory: updated.rootDirectory }));
  } catch (error) {
    await restore();
    throw error;
  }
}

if (action === "preview" || action === "production") {
  const commit = process.env.RELEASE_SHA;
  if (!/^[0-9a-f]{40}$/.test(commit || "")) throw new Error("An exact release commit is required");
  if (Number(project.link?.repoId) !== 1420201479 || project.rootDirectory !== "landing") throw new Error("Migrate the Vercel project to Atlas before deployment");
  const created = await request("/v13/deployments", "POST", {
    name: project.name,
    project: project.id,
    ...(action === "production" ? { target: "production" } : {}),
    gitSource: { type: "github", repoId: "1420201479", ref: "main", sha: commit },
  });
  writeFileSync("dist/deployments/landing-deployment.json", `${JSON.stringify({ id: created.id, url: created.url, commit, target: action }, null, 2)}\n`);
  let previous;
  for (let attempt = 0; attempt < 120; attempt++) {
    const deployment = await request(`/v13/deployments/${created.id}`);
    if (deployment.readyState !== previous) console.log(`Landing ${created.id}: ${deployment.readyState}`);
    previous = deployment.readyState;
    if (deployment.readyState === "READY") {
      if (deployment.meta?.githubCommitSha !== commit) throw new Error("Deployment source commit differs from the release");
      console.log(`Ready: https://${deployment.url}`);
      break;
    }
    if (["ERROR", "CANCELED"].includes(deployment.readyState)) throw new Error(`Landing deployment ${deployment.readyState}`);
    if (attempt === 119) throw new Error("Landing deployment readiness timed out");
    await new Promise(resolve => setTimeout(resolve, 5000));
  }
}
