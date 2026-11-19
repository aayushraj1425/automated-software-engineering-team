import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DeploymentPanel } from "./deployment-panel";

type Run = React.ComponentProps<typeof DeploymentPanel>["run"];

function renderPanel(run: Partial<Run>, extra: { busy?: boolean; error?: string | null } = {}) {
  const onDecide = vi.fn();
  render(
    <DeploymentPanel
      run={{
        status: "executing",
        deployment_status: "not_requested",
        preview_deployment: null,
        preview_requested: null,
        ...run,
      }}
      busy={extra.busy ?? false}
      error={extra.error ?? null}
      onDecide={onDecide}
    />,
  );
  return onDecide;
}

describe("DeploymentPanel", () => {
  it("shows nothing for a run that never asked for a preview", () => {
    renderPanel({});
    expect(screen.queryByLabelText("Preview deployment")).not.toBeInTheDocument();
  });

  it("offers the second approval while awaiting deploy approval", () => {
    const onDecide = renderPanel({ status: "awaiting_deploy_approval", preview_requested: true });
    fireEvent.click(screen.getByRole("button", { name: "Approve deploy" }));
    expect(onDecide).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByRole("button", { name: "Reject deploy" }));
    expect(onDecide).toHaveBeenLastCalledWith(false);
    expect(screen.getByText(/Nothing is deployed until you approve/)).toBeInTheDocument();
  });

  it("disables both buttons while a decision is saving", () => {
    renderPanel({ status: "awaiting_deploy_approval" }, { busy: true });
    expect(screen.getByRole("button", { name: "Approve deploy" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject deploy" })).toBeDisabled();
  });

  it("shows the checked commit and deployment settings before approval", () => {
    renderPanel({
      status: "awaiting_deploy_approval",
      deployment_source_sha: "0123456789012345678901234567890123456789",
      preview_options: {
        chart_path: "charts/app",
        image: "registry.example/app:review",
        ttl_hours: 2,
        smoke_paths: ["/health", "/ready"],
      },
    });
    expect(screen.getByText("0123456789012345678901234567890123456789")).toBeInTheDocument();
    expect(screen.getByText("charts/app")).toBeInTheDocument();
    expect(screen.getByText("registry.example/app:review")).toBeInTheDocument();
    expect(screen.getByText("2 hours")).toBeInTheDocument();
    expect(screen.getByText("/health, /ready")).toBeInTheDocument();
  });

  it("has no approval buttons once the run moved past the gate", () => {
    renderPanel({ status: "deploying", deployment_status: "approved" });
    expect(screen.queryByRole("button", { name: "Approve deploy" })).not.toBeInTheDocument();
    expect(screen.getByText(/Deploying the preview/)).toBeInTheDocument();
  });

  it("links a live preview and lists smoke evidence", () => {
    renderPanel({
      status: "completed",
      deployment_status: "deployed",
      preview_deployment: {
        status: "deployed",
        url: "https://preview.example.com",
        namespace: "asep-preview-1",
        source_sha: "0123456789abcdef",
        smoke: { passed: true, checks: [{ path: "/healthz", ok: true, status_code: 200 }] },
      },
    });
    expect(screen.getByRole("link", { name: "https://preview.example.com" })).toHaveAttribute(
      "href",
      "https://preview.example.com",
    );
    expect(screen.getByText("Live preview environment")).toBeInTheDocument();
    expect(screen.getByText("Cloud smoke tests:")).toBeInTheDocument();
    expect(screen.getByText("/healthz")).toBeInTheDocument();
    expect(screen.getByText("0123456789ab")).toBeInTheDocument();
  });

  it("labels a simulated preview and does not link its URL", () => {
    renderPanel({
      status: "completed",
      deployment_status: "deployed",
      preview_deployment: {
        status: "simulated",
        url: "https://simulated.invalid",
        smoke: { passed: true, checks: [] },
      },
    });
    expect(screen.getByRole("note")).toHaveTextContent(/Simulated, no real cloud deploy/);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Simulated smoke tests:")).toBeInTheDocument();
    expect(screen.queryByText("Live preview environment")).not.toBeInTheDocument();
  });

  it("shows a failed deploy's error and no link", () => {
    renderPanel({
      status: "failed",
      deployment_status: "failed",
      preview_deployment: { status: "failed", url: "https://x.example.com", error: "helm failed" },
    });
    expect(screen.getByText("helm failed")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the engine's refusal of a deploy decision", () => {
    renderPanel(
      { status: "awaiting_deploy_approval" },
      { error: "Only the run owner may approve" },
    );
    expect(screen.getByText("Only the run owner may approve")).toBeInTheDocument();
  });
});
