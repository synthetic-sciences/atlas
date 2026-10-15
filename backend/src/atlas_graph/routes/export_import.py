"""
Export / Import routes -- serialise and restore research subgraphs.
"""

from __future__ import annotations

import base64
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from atlas_graph.dependencies import get_current_user, get_db
from atlas_graph.services import export_import_service, node_service

router = APIRouter()


def _safe_pdf_text(value: str) -> str:
    return value.encode("latin-1", "replace").decode("latin-1")


def _markdown_to_pdf(markdown: str, title: str = "Thesis Export") -> bytes:
    """Convert basic markdown to a PDF document using fpdf2.

    Handles headings (h1-h3), paragraphs, and blank-line spacing. Latin-1
    coerced via _safe_pdf_text so fpdf's core fonts don't blow up on
    unicode input. Returns raw PDF bytes.
    """
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(_safe_pdf_text(title))
    pdf.set_font("Helvetica", size=10)
    for raw_line in markdown.splitlines():
        line = _safe_pdf_text(raw_line)
        if line.startswith("### "):
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 8, line[4:])
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.multi_cell(0, 9, line[3:])
            pdf.set_font("Helvetica", size=10)
        elif line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 10, line[2:])
            pdf.set_font("Helvetica", size=10)
        elif line.strip():
            pdf.multi_cell(0, 6, line)
        else:
            pdf.ln(3)
    output = pdf.output()
    if isinstance(output, bytes):
        return output
    if isinstance(output, bytearray):
        return bytes(output)
    return str(output).encode("latin-1", "replace")


# ---- Request bodies -------------------------------------------------------

class ExportSubgraphRequest(BaseModel):
    node_ids: list[str]
    include_descendants: bool = True
    max_nodes: int | None = None


class ImportSubgraphRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    exported_at: str | None = None
    node_count: int | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    normalize_cycles: bool = False

    @model_validator(mode="before")
    @classmethod
    def unwrap_payload(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("payload", "export", "subgraph", "data"):
                wrapped = value.get(key)
                if isinstance(wrapped, dict) and "nodes" in wrapped:
                    merged = {**wrapped}
                    if "normalize_cycles" in value and "normalize_cycles" not in merged:
                        merged["normalize_cycles"] = value["normalize_cycles"]
                    return merged
        return value


class ExportSummaryRequest(BaseModel):
    node_ids: list[str]
    format: str = "markdown"


class ExportHistoryRequest(BaseModel):
    node_ids: list[str]
    include_descendants: bool = False
    max_nodes: int | None = 200
    limit_per_node: int = 50


# ---- POST /api/export/subgraph -------------------------------------------

@router.post("/api/export/subgraph")
async def export_subgraph(
    req: ExportSubgraphRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await export_import_service.export_subgraph(
            db,
            user["user_id"],
            req.node_ids,
            include_descendants=req.include_descendants,
            max_nodes=req.max_nodes,
        )
    except ValueError as e:
        msg = str(e)
        if "Access denied" in msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=msg
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=msg
        )


# ---- POST /api/export/history --------------------------------------------

@router.post("/api/export/history")
async def export_history(
    req: ExportHistoryRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await export_import_service.export_history(
            db,
            user["user_id"],
            req.node_ids,
            include_descendants=req.include_descendants,
            max_nodes=req.max_nodes,
            limit_per_node=req.limit_per_node,
        )
    except ValueError as e:
        msg = str(e)
        if "Access denied" in msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


# ---- POST /api/import/subgraph -------------------------------------------

@router.post("/api/import/subgraph", status_code=status.HTTP_201_CREATED)
async def import_subgraph(
    req: ImportSubgraphRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await export_import_service.import_subgraph(
            db, user["user_id"], req.model_dump()
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )


# ---- POST /api/export/summary --------------------------------------------

@router.post("/api/export/summary")
async def export_summary(
    req: ExportSummaryRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Generate a markdown summary of the specified nodes and their subtrees."""
    node_ids = req.node_ids
    sections: list[str] = []

    for nid in node_ids:
        try:
            tree = await node_service.get_node_tree(
                db, user["user_id"], nid, projection="full", max_nodes=200
            )
        except ValueError:
            sections.append(f"## Node {nid}\n\n_Node not found._\n")
            continue

        for node in tree.get("nodes", []):
            title = node.get("title") or node.get("slug_name") or node.get("node_id")
            kind = node.get("kind", "untyped")
            lifecycle = node.get("lifecycle", "staged")
            outcome = node.get("outcome", "")
            summary = node.get("summary") or ""

            header = f"## {title}"
            meta_parts = [f"kind={kind}", f"lifecycle={lifecycle}"]
            if outcome:
                meta_parts.append(f"outcome={outcome}")
            meta = " | ".join(meta_parts)

            block = f"{header}\n\n_{meta}_\n"
            if summary:
                block += f"\n{summary}\n"
            sections.append(block)

    markdown = (
        "# Research Summary\n\n" + "\n---\n\n".join(sections)
        if sections
        else "# Research Summary\n\nNo nodes found.\n"
    )

    return {
        "format": req.format,
        "content": markdown,
        "node_count": len(node_ids),
    }


# ---- POST /api/export/summary/pdf ----------------------------------------

class ExportSummaryPdfRequest(BaseModel):
    node_ids: list[str]


@router.post("/api/export/summary/pdf")
async def export_summary_pdf(
    req: ExportSummaryPdfRequest,
    db: aiosqlite.Connection = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Generate a PDF summary and return raw PDF bytes."""
    # Re-use the summary endpoint logic to get markdown
    summary_req = ExportSummaryRequest(node_ids=req.node_ids, format="markdown")
    summary_result = await export_summary(summary_req, db=db, user=user)
    markdown = summary_result.get("content", "")
    pdf_bytes = await run_in_threadpool(
        _markdown_to_pdf, markdown, title="Thesis Export"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=thesis-summary.pdf"},
    )
