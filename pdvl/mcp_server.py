"""Optional local STDIO MCP interface. No remote unauthenticated server."""

def main():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise SystemExit("Install optional dependency: pip install -e '.[mcp]'")
    from .db import init_db, one, rows
    from .api import project_required
    init_db()
    mcp = FastMCP("PDVL Research Memory")

    @mcp.tool()
    def list_projects() -> list[dict]:
        """List research projects available in this local PDVL repository."""
        return rows("SELECT * FROM projects ORDER BY created_at DESC")

    @mcp.tool()
    def get_project_brief(project_id: str) -> dict:
        """Return verified and unresolved claims with evidence references."""
        from .api import scientific_brief
        return scientific_brief(project_id)

    @mcp.tool()
    def research_search(project_id: str, search_text: str) -> dict:
        """Search research claims and evidence. Read-only and scoped to project."""
        project_required(project_id)
        pattern = f"%{search_text[:180]}%"
        return {
            "claims": rows("SELECT * FROM claims WHERE project_id=? AND (statement LIKE ? OR title LIKE ?) LIMIT 30", (project_id,pattern,pattern)),
            "evidence": rows("SELECT * FROM evidence WHERE project_id=? AND description LIKE ? LIMIT 30", (project_id,pattern)),
        }

    mcp.run(transport="stdio")
