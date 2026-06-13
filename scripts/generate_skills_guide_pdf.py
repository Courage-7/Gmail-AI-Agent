"""Generate a PDF guide for installed project skills."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs"
OUT_PDF = OUT_DIR / "email-agent-skills-guide.pdf"

INK = colors.HexColor("#18212F")
BLUE = colors.HexColor("#2E74B5")
DARK_BLUE = colors.HexColor("#1F4D78")
MUTED = colors.HexColor("#64748B")
LIGHT_BLUE = colors.HexColor("#E8EEF5")
LIGHT_GRAY = colors.HexColor("#F8FAFC")
SUCCESS = colors.HexColor("#DCFCE7")
WARNING = colors.HexColor("#FEF3C7")
ERROR_FILL = colors.HexColor("#FEE2E2")
BORDER = colors.HexColor("#CBD5E1")


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT_PDF),
        pagesize=LETTER,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
        title="Email Agent Skills Guide",
        author="Codex",
    )
    styles = build_styles()
    story = build_story(styles)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUT_PDF)


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "GuideTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=colors.HexColor("#0F172A"),
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "GuideSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
            textColor=MUTED,
            spaceAfter=10,
        ),
        "meta": ParagraphStyle(
            "GuideMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "GuideHeading1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=BLUE,
            spaceBefore=14,
            spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "GuideHeading2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=15,
            textColor=DARK_BLUE,
            spaceBefore=9,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "GuideBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=12.5,
            textColor=INK,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "GuideSmall",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=10.5,
            textColor=INK,
        ),
        "table_header": ParagraphStyle(
            "GuideTableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.2,
            leading=10.5,
            textColor=INK,
        ),
        "code": ParagraphStyle(
            "GuideCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#0F172A"),
        ),
        "callout": ParagraphStyle(
            "GuideCallout",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12,
            textColor=INK,
        ),
    }


def build_story(styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    story.append(Paragraph("Email Agent Skills Guide", styles["title"]))
    story.append(
        Paragraph(
            "Installation status, project startup, and design workflow for the visual workflow builder",
            styles["subtitle"],
        )
    )
    story.append(
        Paragraph("Project: email-agent | Scope: Graphify, UI/UX Pro Max, Framer Motion", styles["meta"])
    )

    story.append(
        callout(
            [
                p(
                    "<b>Current position:</b> Graphify and UI/UX Pro Max are installed in the user-level Codex skills folder. "
                    "Framer Motion is planned for the frontend project, but the package download was blocked by the current approval limit.",
                    styles["callout"],
                )
            ],
            LIGHT_BLUE,
        )
    )

    heading(story, "1. Installation Status", styles)
    story.append(status_table(styles))

    heading(story, "2. What Each Tool Adds", styles)
    story.append(
        bullets(
            [
                "Graphify turns the project into a queryable knowledge graph for architecture and file-relationship questions.",
                "UI/UX Pro Max gives design intelligence for layout, visual hierarchy, responsive behavior, colors, component choices, and UX heuristics.",
                "Framer Motion adds animation primitives after it is installed in the Vite frontend. Use it for feedback and clarity, not decoration.",
                "21st.dev Magic MCP can be considered later when you have an API key and want generated UI components.",
            ],
            styles,
        )
    )

    heading(story, "3. Installation Guide", styles)
    subheading(story, "Graphify", styles)
    story.append(code_block(["uv tool install graphifyy", r"C:\Users\coura\.local\bin\graphify.exe install --platform codex", r"C:\Users\coura\.local\bin\graphify.exe --version"], styles))
    story.append(bullets([r"Installed skill path: C:\Users\coura\.codex\skills\graphify", r"Note: C:\Users\coura\.local\bin is not currently on PATH. Use the absolute graphify.exe path or update PATH later."], styles))

    subheading(story, "UI/UX Pro Max", styles)
    story.append(code_block(["npm install -g uipro-cli", "uipro init --ai codex", r"Copy project skill folder to C:\Users\coura\.codex\skills\ui-ux-pro-max if needed", "uipro --version"], styles))
    story.append(bullets([r"Installed skill path: C:\Users\coura\.codex\skills\ui-ux-pro-max", r"The installer also created a project-local copy at .codex/skills/ui-ux-pro-max."], styles))

    subheading(story, "Framer Motion", styles)
    story.append(code_block(["cd frontend", "npm install framer-motion", "npm run build"], styles))
    story.append(
        callout(
            [
                p(
                    "<b>Status:</b> not installed yet because external package download approval is currently blocked. "
                    "Run the commands above once approvals are available.",
                    styles["callout"],
                )
            ],
            ERROR_FILL,
        )
    )

    heading(story, "4. How To Start Them In This Project", styles)
    story.append(start_table(styles))

    heading(story, "5. Professional Frontend Workflow", styles)
    story.append(
        Paragraph(
            "Yes, we can use these tools to design the workflow-builder frontend professionally. The clean order is:",
            styles["body"],
        )
    )
    story.append(
        numbered(
            [
                "Use Graphify when we need a project map before changing contracts, routes, runtime adapters, or component boundaries.",
                "Use UI/UX Pro Max before a visual polish pass. It should guide density, hierarchy, typography, validation states, and responsive behavior.",
                "Install Framer Motion after the builder and validation loop are stable. Use motion for node status, validation feedback, and panel transitions.",
                "Keep React Flow as the canvas interaction engine. Framer Motion should enhance surrounding UI and workflow state, not fight the canvas.",
            ],
            styles,
        )
    )

    subheading(story, "Recommended animation rules", styles)
    story.append(
        bullets(
            [
                "Prefer subtle 120-220 ms transitions for panels, alerts, status badges, and validation results.",
                "Use clear state changes over decorative motion. This builder is an operational tool.",
                "Respect reduced-motion settings.",
                "Avoid animating every node constantly. Reserve motion for direct manipulation, run state, and validation feedback.",
            ],
            styles,
        )
    )

    heading(story, "6. Operating Rules Before We Continue", styles)
    story.append(
        bullets(
            [
                "Restart Codex before expecting newly installed skills to appear in the available skills list.",
                "Do not expose raw MCP, Gmail, or internal tool execution from the browser. The backend registry stays authoritative.",
                "Use the skills as design and architecture accelerators, not as permission to skip tests, validation, or browser verification.",
                "Next implementation step after restart: connect the builder to backend validation cleanly, then polish the UX with UI/UX Pro Max guidance.",
            ],
            styles,
        )
    )

    return story


def status_table(styles: dict[str, ParagraphStyle]) -> Table:
    data = [
        ["Tool", "Status", "Where", "What it is for"],
        [
            "Graphify",
            "Installed",
            r"C:\Users\coura\.codex\skills\graphify",
            "Build and query a knowledge graph before architecture-heavy work.",
        ],
        [
            "UI/UX Pro Max",
            "Installed",
            r"C:\Users\coura\.codex\skills\ui-ux-pro-max",
            "Professional frontend layout, hierarchy, colors, UX, and component decisions.",
        ],
        [
            "Framer Motion",
            "Pending package install",
            r"frontend/package.json",
            "React animation library for polished transitions and workflow feedback.",
        ],
        [
            "21st.dev Magic MCP",
            "Skipped for now",
            "Needs API key",
            "Optional component-generation MCP for later.",
        ],
    ]
    return styled_table(data, [1.15 * inch, 1.2 * inch, 1.95 * inch, 2.2 * inch], styles, status_column=1)


def start_table(styles: dict[str, ParagraphStyle]) -> Table:
    data = [
        ["Tool", "Start command or trigger", "Good first use in email-agent"],
        [
            "Graphify",
            "After Codex restart, invoke the graphify skill for codebase questions. CLI docs also show: /graphify .",
            "Map FastAPI routes, workflow registry, frontend components, and future LangGraph adapter boundaries.",
        ],
        [
            "UI/UX Pro Max",
            "After Codex restart, ask Codex to use ui-ux-pro-max for frontend design and UX polish.",
            "Audit node palette, canvas, config panel, validation states, empty states, and responsive layout.",
        ],
        [
            "Framer Motion",
            "After package install: import { motion, AnimatePresence } from 'framer-motion'.",
            "Animate node status changes, validation feedback, panel transitions, and run-event output.",
        ],
    ]
    return styled_table(data, [1.25 * inch, 2.5 * inch, 2.75 * inch], styles)


def styled_table(data: list[list[str]], widths: list[float], styles: dict[str, ParagraphStyle], status_column: int | None = None) -> Table:
    formatted = []
    for row_idx, row in enumerate(data):
        formatted_row = []
        for value in row:
            formatted_row.append(Paragraph(value, styles["table_header"] if row_idx == 0 else styles["small"]))
        formatted.append(formatted_row)

    table = Table(formatted, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table_style = [
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if status_column is not None:
        for row_idx, row in enumerate(data[1:], start=1):
            fill = SUCCESS if row[status_column] == "Installed" else WARNING
            table_style.append(("BACKGROUND", (status_column, row_idx), (status_column, row_idx), fill))
    table.setStyle(TableStyle(table_style))
    return table


def heading(story: list, text: str, styles: dict[str, ParagraphStyle]) -> None:
    story.append(Spacer(1, 6))
    story.append(Paragraph(text, styles["h1"]))


def subheading(story: list, text: str, styles: dict[str, ParagraphStyle]) -> None:
    story.append(Paragraph(text, styles["h2"]))


def bullets(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, styles["body"]), leftIndent=12) for item in items],
        bulletType="bullet",
        start="circle",
        leftIndent=16,
        bulletFontSize=7,
    )


def numbered(items: list[str], styles: dict[str, ParagraphStyle]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(item, styles["body"]), leftIndent=12) for item in items],
        bulletType="1",
        leftIndent=16,
    )


def code_block(lines: list[str], styles: dict[str, ParagraphStyle]) -> Table:
    content = "<br/>".join(escape(line) for line in lines)
    return callout([Paragraph(content, styles["code"])], LIGHT_GRAY)


def callout(flowables: list, fill_color) -> Table:
    table = Table([[flowables]], colWidths=[6.5 * inch], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), fill_color),
                ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(7.5 * inch, 0.5 * inch, f"Email Agent Skills Guide | Page {doc.page}")
    canvas.restoreState()


if __name__ == "__main__":
    main()
