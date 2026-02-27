"""Generate euAIKG technical presentation (6 slides)."""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

DOCS = Path(__file__).parent
OUT = DOCS / "euAIKG_technical.pptx"

# Slide dimensions: 16:9
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# Colors
DARK = RGBColor(0x1A, 0x1A, 0x2E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0x66, 0x66, 0x66)
ACCENT = RGBColor(0x1E, 0x88, 0xE5)


def set_slide_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_title(slide, text, left, top, width, height, size=32, color=DARK, bold=True):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(size)
    p.font.color.rgb = color
    p.font.bold = bold
    return tf


def add_body(slide, lines, left, top, width, height, size=14, color=DARK, spacing=1.2):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.text = line
        p.font.size = Pt(size)
        p.font.color.rgb = color
        p.space_after = Pt(size * spacing * 0.4)
    return tf


def add_subtitle(slide, text, left, top, width, height, size=16, color=ACCENT):
    return add_title(slide, text, left, top, width, height, size=size, color=color, bold=True)


def add_image_centered(slide, img_path, top, max_w, max_h):
    """Add image centered horizontally, fitting within max_w x max_h."""
    from PIL import Image
    img = Image.open(img_path)
    iw, ih = img.size
    ratio = min(max_w / iw, max_h / ih)
    w = int(iw * ratio)
    h = int(ih * ratio)
    left = (SLIDE_W - Emu(w * 914400 // 96)) // 2  # center
    slide.shapes.add_picture(str(img_path), left, top, Emu(w * 914400 // 96), Emu(h * 914400 // 96))


def make_pptx():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]  # blank layout

    # ================================================================
    # SLIDE 1 — Architecture
    # ================================================================
    s1 = prs.slides.add_slide(blank)
    set_slide_bg(s1, WHITE)
    add_title(s1, "System Architecture", Inches(0.8), Inches(0.3), Inches(11), Inches(0.7), size=30)
    add_body(s1, [
        "EU AI Act Text -> LLM Graph Extraction -> Neo4j -> Web Dashboard",
        "",
        "- Backend: Neo4j (Graph DB) + vLLM / Gemini API (Compute Engine)",
        "- Frontend: Flask + Cytoscape.js (Single Page Dashboard)",
        "- Resumable pipeline with CLI / Web dual execution mode",
    ], Inches(0.8), Inches(1.1), Inches(5.5), Inches(2.0), size=13)

    img1 = DOCS / "slide1_architecture.png"
    if img1.exists():
        s1.shapes.add_picture(str(img1), Inches(0.5), Inches(3.3), Inches(12.3))

    # ================================================================
    # SLIDE 2 — Principles
    # ================================================================
    s2 = prs.slides.add_slide(blank)
    set_slide_bg(s2, WHITE)
    add_title(s2, "Design Principles", Inches(0.8), Inches(0.3), Inches(11), Inches(0.7), size=30)

    principles = [
        ("Dual-LLM Robustness",
         "Local vLLM for throughput, Gemini API fallback for failed chunks\n"
         "-> Cost efficiency + extraction completeness"),
        ("Graph-Native Storage",
         "Entity relationships as first-class citizens in Neo4j\n"
         "Native graph algorithms (KNN, WCC) via GDS plugin"),
        ("LLM-Assisted Entity Resolution",
         "Embedding similarity + text distance for candidate narrowing\n"
         "Gemini structured output for final merge judgment"),
        ("Resumable Pipeline",
         "Checkpoint per phase (pickle existence, node count, WCC property)\n"
         "Resume after interruption without reprocessing"),
    ]

    for i, (title, desc) in enumerate(principles):
        col = i % 2
        row = i // 2
        left = Inches(0.8 + col * 6.2)
        top = Inches(1.3 + row * 2.8)
        # Card background
        shape = s2.shapes.add_shape(
            1, left, top, Inches(5.6), Inches(2.3)  # 1 = rectangle
        )
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(0xF5, 0xF6, 0xF8)
        shape.line.fill.background()
        shape.shadow.inherit = False

        add_subtitle(s2, f"{i+1}. {title}", left + Inches(0.3), top + Inches(0.2),
                     Inches(5.0), Inches(0.5), size=16)
        add_body(s2, desc.split("\n"), left + Inches(0.3), top + Inches(0.8),
                 Inches(5.0), Inches(1.3), size=12, color=GRAY)

    # ================================================================
    # SLIDE 3 — Methodology 1
    # ================================================================
    s3 = prs.slides.add_slide(blank)
    set_slide_bg(s3, WHITE)
    add_title(s3, "Methodology — Graph Extraction & Ingestion", Inches(0.8), Inches(0.3),
              Inches(11), Inches(0.7), size=28)

    add_body(s3, [
        "Graph Extraction",
        "  - LLMGraphTransformer: auto-extract entities & relations from text chunks",
        "  - 4-thread parallel, 300s timeout per chunk",
        "  - vLLM (Qwen3-14B-AWQ) primary + Gemini API fallback",
        "",
        "Ingestion",
        "  - Deserialized GraphDocuments bulk-loaded into Neo4j",
        "  - __Entity__ common label + MENTIONS source reference",
    ], Inches(0.8), Inches(1.1), Inches(5.0), Inches(2.5), size=12)

    img3 = DOCS / "slide3_extraction.png"
    if img3.exists():
        s3.shapes.add_picture(str(img3), Inches(0.3), Inches(4.0), Inches(12.5))

    # ================================================================
    # SLIDE 4 — Methodology 2
    # ================================================================
    s4 = prs.slides.add_slide(blank)
    set_slide_bg(s4, WHITE)
    add_title(s4, "Methodology — Community Detection & Entity Resolution", Inches(0.8), Inches(0.3),
              Inches(11), Inches(0.7), size=28)

    add_body(s4, [
        "Step 1: Embedding",
        "  - multilingual-e5-large -> 1024-dim vector per entity",
        "",
        "Step 2: Community Detection (GDS)",
        "  - KNN: cosine similarity >= 0.95 -> SIMILAR relationship",
        "  - WCC: connected components -> community ID",
        "",
        "Step 3: Entity Resolution",
        "  - Candidate filtering: APOC text edit distance <= 3",
        "  - Gemini structured output (Pydantic schema) for merge judgment",
        "  - APOC mergeNodes for duplicate removal",
    ], Inches(0.8), Inches(1.1), Inches(5.5), Inches(3.0), size=12)

    img4 = DOCS / "slide4_community.png"
    if img4.exists():
        s4.shapes.add_picture(str(img4), Inches(0.3), Inches(4.5), Inches(12.5))

    # ================================================================
    # SLIDE 5 — Results 1 (Dashboard)
    # ================================================================
    s5 = prs.slides.add_slide(blank)
    set_slide_bg(s5, WHITE)
    add_title(s5, "Results — Interactive Dashboard", Inches(0.8), Inches(0.3),
              Inches(11), Inches(0.7), size=30)

    add_body(s5, [
        "- Pipeline control + graph visualization + real-time log in single dashboard",
        "- SSE-based live log streaming, auto-refresh on pipeline completion",
        "- 5 layout algorithms, pan/zoom interaction",
    ], Inches(0.8), Inches(1.0), Inches(11), Inches(1.2), size=13)

    img_overview = DOCS / "screenshot_graph_overview.png"
    img_detail = DOCS / "screenshot_graph_detail.png"
    if img_overview.exists():
        s5.shapes.add_picture(str(img_overview), Inches(0.5), Inches(2.5), Inches(6.0))
    if img_detail.exists():
        s5.shapes.add_picture(str(img_detail), Inches(6.8), Inches(2.5), Inches(6.0))

    # Caption
    add_body(s5, [
        "Left: Full knowledge graph network view          Right: Entity relationship detail view"
    ], Inches(0.8), Inches(6.8), Inches(11), Inches(0.5), size=11, color=GRAY)

    # ================================================================
    # SLIDE 6 — Results 2 (Stats)
    # ================================================================
    s6 = prs.slides.add_slide(blank)
    set_slide_bg(s6, WHITE)
    add_title(s6, "Results — Pipeline Output", Inches(0.8), Inches(0.3),
              Inches(11), Inches(0.7), size=30)

    # Table
    rows, cols = 7, 2
    tbl_shape = s6.shapes.add_table(rows, cols, Inches(1.5), Inches(1.5), Inches(7), Inches(3.5))
    tbl = tbl_shape.table

    headers = ["Item", "Value"]
    data = [
        ("Input Document", "EU AI Act (full text)"),
        ("Chunking", "Qwen3 tokenizer, 350 tok / 75 overlap"),
        ("Extraction Strategy", "vLLM primary + Gemini fallback"),
        ("Final Nodes", "475 (__Entity__)"),
        ("Final Edges", "500 (relationships)"),
        ("Entity Resolution", "KNN+WCC community detection -> Gemini -> APOC merge"),
    ]

    for ci, h in enumerate(headers):
        cell = tbl.cell(0, ci)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.size = Pt(13)
            p.font.bold = True
            p.font.color.rgb = WHITE
        cell.fill.solid()
        cell.fill.fore_color.rgb = DARK

    for ri, (k, v) in enumerate(data, start=1):
        for ci, val in enumerate([k, v]):
            cell = tbl.cell(ri, ci)
            cell.text = val
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(12)
                p.font.color.rgb = DARK
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0xF5, 0xF6, 0xF8) if ri % 2 == 0 else WHITE

    # Key achievements
    add_subtitle(s6, "Key Achievements", Inches(1.5), Inches(5.3), Inches(7), Inches(0.4), size=16)
    add_body(s6, [
        "- Automated conversion of EU AI Act into structured knowledge graph",
        "- Dual-LLM strategy reduced extraction failure rate vs single model",
        "- Community-based entity resolution removed duplicate nodes, improving graph quality",
    ], Inches(1.5), Inches(5.8), Inches(9), Inches(1.5), size=12)

    # ── Save ──
    prs.save(str(OUT))
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    make_pptx()
