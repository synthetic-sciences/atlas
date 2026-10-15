import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MemoryRouter } from "react-router-dom";
import type { GraphTag, Node, SharingInfo } from "../../api/types";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  listAudit: vi.fn(),
  getSharing: vi.fn(),
  setSharing: vi.fn(),
  getNode: vi.fn(),
  createTag: vi.fn(),
  deleteTag: vi.fn(),
  setTagAssignments: vi.fn(),
}));

vi.mock("../../api/internal", () => ({
  BASE_URL: "/api",
  getAuthHeaders: vi.fn().mockResolvedValue({}),
  request: (...args: unknown[]) => mocks.request(...args),
  publicRequest: vi.fn(),
  qs: vi.fn(() => ""),
}));

vi.mock("../../api/client", () => ({
  api: {
    listAudit: (...args: unknown[]) => mocks.listAudit(...args),
    getSharing: (...args: unknown[]) => mocks.getSharing(...args),
    setSharing: (...args: unknown[]) => mocks.setSharing(...args),
    getNode: (...args: unknown[]) => mocks.getNode(...args),
    createTag: (...args: unknown[]) => mocks.createTag(...args),
    deleteTag: (...args: unknown[]) => mocks.deleteTag(...args),
    setTagAssignments: (...args: unknown[]) => mocks.setTagAssignments(...args),
  },
}));

import { nodesApi } from "../../api/nodes";
import { NodeSidebar } from "./NodeSidebar";

const sharingInfo: SharingInfo = {
  node_id: "root-1",
  project_id: "root-1",
  requested_node_id: "child-1",
  owner_user_id: "owner-1",
  owner_email: "owner@example.com",
  is_owner: true,
  collaboration_enabled: true,
  sharing_mode: "private",
  visibility: "private",
  effective: { can_view: true, can_write: true, can_admin: true },
  collaborators: [],
  updated_at: "2026-07-13T00:00:00Z",
};

const tag: GraphTag = {
  tag_id: "tag-1",
  name: "Alpha",
  bg_color: "#112233",
  text_color: "#ffffff",
  one_only: false,
  track_history: false,
};

function node(overrides: Partial<Node> = {}): Node {
  return {
    node_id: "root-1",
    slug_name: "root-one",
    title: "Root",
    summary: null,
    content: null,
    updated_by: null,
    kind: "insight",
    lifecycle: "staged",
    outcome: "completed",
    hypothesis: null,
    no_artifacts_reason: null,
    insights: ["one"],
    parent_ids: [],
    child_ids: ["child-1"],
    repo_url: null,
    branch_name: null,
    head_commit_sha: null,
    origin_host: null,
    external_transcript_ref: null,
    revision: 11,
    graph_tags: [],
    tag_ids: [],
    tag_history: [],
    semantic_data: null,
    created_at: "2026-07-13T00:00:00Z",
    updated_at: "2026-07-13T00:00:00Z",
    ...overrides,
  } as Node;
}

function props(overrides: Partial<Parameters<typeof NodeSidebar>[0]> = {}) {
  return {
    nodeId: "child-1",
    staged: true,
    allOk: false,
    checklist: [],
    actLoad: null,
    repoUrl: null,
    branchName: null,
    headCommitSha: null,
    revision: 7,
    graphTags: [],
    assignedTagIds: [],
    contractWarnings: [],
    slugName: "child-one",
    kind: "insight",
    outcome: "completed",
    semanticData: null,
    artifacts: [],
    onCommit: vi.fn(),
    onBranch: vi.fn(),
    onDelete: vi.fn(),
    onRefresh: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } satisfies Parameters<typeof NodeSidebar>[0];
}

function renderSidebar(overrides: Partial<Parameters<typeof NodeSidebar>[0]> = {}) {
  return render(
    <MemoryRouter>
      <NodeSidebar {...props(overrides)} />
    </MemoryRouter>,
  );
}

function openSection(name: string) {
  const label = screen.getByText(name, { exact: true });
  fireEvent.click(label.closest("button")!);
}

describe("browser node mutation contracts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listAudit.mockResolvedValue([]);
    mocks.getSharing.mockResolvedValue(sharingInfo);
    mocks.getNode.mockResolvedValue(node());
    mocks.createTag.mockResolvedValue({ tag, node: node({ graph_tags: [tag], revision: 12 }) });
    mocks.deleteTag.mockResolvedValue(undefined);
    mocks.setTagAssignments.mockResolvedValue(node({ node_id: "child-1", tag_ids: [tag.tag_id], revision: 8 }));
    mocks.setSharing.mockImplementation(async (_nodeId: string, update: Partial<SharingInfo>) => ({
      ...sharingInfo,
      ...update,
    }));
  });

  it("unwraps the backend branch envelope before returning the child node", async () => {
    const child = node({ node_id: "child-2", parent_ids: ["root-1"], revision: 0 });
    const payload = { node_id: "root-1", expected_revision: 11, title: "Child" };
    mocks.request.mockResolvedValueOnce({ node: child, parent_revision: 12 });

    await expect(nodesApi.branchNode(payload)).resolves.toEqual(child);
    expect(mocks.request).toHaveBeenCalledWith("/nodes/branch", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  });

  it("creates graph tags against the fresh root revision", async () => {
    const { container } = renderSidebar();
    openSection("tags");
    fireEvent.click(screen.getByText("+ New label", { exact: true }));
    fireEvent.change(screen.getByPlaceholderText("Label name"), { target: { value: "Alpha" } });
    const colors = container.querySelectorAll<HTMLInputElement>('input[type="color"]');
    fireEvent.change(colors[0], { target: { value: "#112233" } });
    fireEvent.change(colors[1], { target: { value: "#ffffff" } });
    fireEvent.click(screen.getByRole("button", { name: "Create label" }));

    await waitFor(() => {
      expect(mocks.getNode).toHaveBeenCalledWith("root-1", "core", { fresh: true });
      expect(mocks.createTag).toHaveBeenCalledWith({
        root_node_id: "root-1",
        expected_revision: 11,
        name: "Alpha",
        bg_color: "#112233",
        text_color: "#ffffff",
      });
    });
  });

  it("includes the current node revision when assigning a tag", async () => {
    renderSidebar({ graphTags: [tag] });
    openSection("tags");
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));

    await waitFor(() => {
      expect(mocks.setTagAssignments).toHaveBeenCalledWith({
        node_id: "child-1",
        expected_revision: 7,
        tag_ids: ["tag-1"],
      });
    });
  });

  it("deletes graph tags against the fresh root revision", async () => {
    renderSidebar({ graphTags: [tag] });
    openSection("tags");
    fireEvent.click(screen.getByTitle("Delete label"));
    fireEvent.click(screen.getByRole("button", { name: "Yes" }));

    await waitFor(() => {
      expect(mocks.deleteTag).toHaveBeenCalledWith({
        root_node_id: "root-1",
        tag_id: "tag-1",
        expected_revision: 11,
      });
    });
  });

  it("keeps visibility private while preserving collaborator mutations", async () => {
    const canonicalCollaborator = { email: "canonical@example.com", role: "editor" as const };
    mocks.setSharing
      .mockResolvedValueOnce({
        ...sharingInfo,
        collaborators: [canonicalCollaborator],
      })
      .mockResolvedValueOnce({ ...sharingInfo, collaborators: [] });

    renderSidebar();
    openSection("sharing");
    expect(await screen.findByRole("button", { name: "private" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "public" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "unlisted" })).not.toBeInTheDocument();

    fireEvent.change(await screen.findByPlaceholderText("email"), {
      target: { value: "viewer@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "add" }));
    await waitFor(() => {
      expect(mocks.setSharing).toHaveBeenNthCalledWith(1, "child-1", {
        node_id: "child-1",
        collaborators: [{ email: "viewer@example.com", role: "viewer" }],
      });
    });
    expect(await screen.findByText("canonical@example.com")).toBeInTheDocument();
    expect(screen.queryByText("viewer@example.com")).not.toBeInTheDocument();

    fireEvent.click(await screen.findByTitle("remove collaborator"));
    await waitFor(() => {
      expect(mocks.setSharing).toHaveBeenNthCalledWith(2, "child-1", {
        node_id: "child-1",
        collaborators: [],
      });
    });
  });

  it("fails closed from the server sharing entitlement without billing catalog calls", async () => {
    mocks.getSharing.mockResolvedValue({
      ...sharingInfo,
      collaboration_enabled: false,
    });

    renderSidebar();
    openSection("sharing");

    expect(
      await screen.findByText(/Private collaboration is/i),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("collaboration coming soon")).toBeDisabled();
    expect(screen.getByRole("button", { name: "add" })).toBeDisabled();
  });

  it("lets a frozen owner revoke an existing collaborator", async () => {
    const existing = { email: "viewer@example.com", role: "viewer" as const };
    mocks.getSharing.mockResolvedValue({
      ...sharingInfo,
      collaboration_enabled: false,
      collaborators: [existing],
    });
    mocks.setSharing.mockResolvedValue({
      ...sharingInfo,
      collaboration_enabled: false,
      collaborators: [],
    });

    renderSidebar();
    openSection("sharing");
    fireEvent.click(await screen.findByTitle("remove collaborator"));

    await waitFor(() => {
      expect(mocks.setSharing).toHaveBeenCalledWith("child-1", {
        node_id: "child-1",
        collaborators: [],
      });
    });
    expect(screen.getByRole("button", { name: "add" })).toBeDisabled();
  });

  it("hides every sharing mutation from a non-admin viewer", async () => {
    mocks.getSharing.mockResolvedValue({
      ...sharingInfo,
      is_owner: false,
      collaboration_enabled: true,
      effective: { can_view: true, can_write: false, can_admin: false },
      collaborators: [{ email: "other@example.com", role: "editor" }],
    });

    renderSidebar();
    openSection("sharing");

    expect(await screen.findByRole("button", { name: "private" })).toBeDisabled();
    expect(screen.getByPlaceholderText("admin access required")).toBeDisabled();
    expect(screen.getByRole("button", { name: "add" })).toBeDisabled();
    expect(screen.queryByTitle("remove collaborator")).not.toBeInTheDocument();
    expect(mocks.setSharing).not.toHaveBeenCalled();
  });
});
