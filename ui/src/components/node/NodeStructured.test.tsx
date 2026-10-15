import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NodeStructured } from "./NodeStructured";

describe("NodeStructured", () => {
  it("surfaces an empirical run's headline metric and code state", () => {
    render(
      <NodeStructured
        node={{
          kind: "empirical",
          outcome: "completed",
          summary: null,
          repo_url: "https://github.com/mutable-state-inc/autoresearch-at-home",
          branch_name: "autoresearch/forge-s0",
          head_commit_sha: "501c2433ab19",
          semantic_data: { type: "run", metrics: { val_bpb: 0.91062, num_steps: 1011 } },
        }}
      />,
    );
    expect(screen.getByText("0.91062")).toBeTruthy();
    expect(screen.getByText(/autoresearch-at-home/)).toBeTruthy();
    expect(screen.getByText(/501c243/)).toBeTruthy();
    // commit links to the github commit page
    const link = screen.getByText(/501c243/).closest("a");
    expect(link?.getAttribute("href")).toContain("/commit/501c2433ab19");
  });

  it("renders a hypothesis's claim and disconfirmers", () => {
    render(
      <NodeStructured
        node={{
          kind: "hypothesis",
          outcome: null,
          summary: null,
          repo_url: null,
          branch_name: null,
          head_commit_sha: null,
          semantic_data: {
            type: "hypothesis",
            status: "supported",
            claim: "n-gram embeddings lower val_bpb",
            disconfirmers: ["fails on 10 seeds"],
          },
        }}
      />,
    );
    expect(screen.getByText("n-gram embeddings lower val_bpb")).toBeTruthy();
    expect(screen.getByText("supported")).toBeTruthy();
    expect(screen.getByText("fails on 10 seeds")).toBeTruthy();
    expect(screen.getByText(/disconfirm/i)).toBeTruthy();
  });

  it("renders a decision's alternatives and confidence", () => {
    render(
      <NodeStructured
        node={{
          kind: "decision",
          outcome: null,
          summary: "Adopt the best config",
          repo_url: null,
          branch_name: null,
          head_commit_sha: null,
          semantic_data: { type: "decision", alternatives: ["keep previous best"], confidence: "high", reversible: true },
        }}
      />,
    );
    expect(screen.getByText("Adopt the best config")).toBeTruthy();
    expect(screen.getByText("keep previous best")).toBeTruthy();
    expect(screen.getByText(/high confidence/)).toBeTruthy();
  });

  it("renders nothing for a plain untyped node", () => {
    const { container } = render(
      <NodeStructured
        node={{ kind: "untyped", outcome: null, summary: "just a note", repo_url: null, branch_name: null, head_commit_sha: null, semantic_data: null }}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
