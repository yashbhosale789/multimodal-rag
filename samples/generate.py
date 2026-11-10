"""Generate the synthetic test corpus. Run from project root: python samples/generate.py

Facts are deliberately split across text, tables and images, and across the two files,
so each pipeline stage has something only it can find. Expected answers: samples/README.md.
"""

import tempfile
from pathlib import Path

import pymupdf
from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
WHITE, BLACK, BLUE, GREY = "white", "black", "#2b6cb0", "#e2e8f0"


def font(size):
    return ImageFont.load_default(size=size)


def shipments_chart(path):
    data = [
        ("Q1", 1200),
        ("Q2", 1850),
        ("Q3", 2400),
        ("Q4", 2950),
    ]  # sums to 8,400 (stated in text)
    img = Image.new("RGB", (800, 500), WHITE)
    d = ImageDraw.Draw(img)
    d.text(
        (400, 30),
        "Acme Corp - Battery Pack Shipments 2025 (units)",
        font=font(24),
        fill=BLACK,
        anchor="mm",
    )
    base, top, maxv = 440, 90, 3200
    for i, (q, v) in enumerate(data):
        x = 130 + i * 160
        y = base - (base - top) * v / maxv
        d.rectangle([x, y, x + 100, base], fill=BLUE)
        d.text((x + 50, y - 18), f"{v:,}", font=font(20), fill=BLACK, anchor="mm")
        d.text((x + 50, base + 22), q, font=font(20), fill=BLACK, anchor="mm")
    d.line([100, base, 760, base], fill=BLACK, width=2)
    img.save(path)


def process_diagram(path):
    steps = [
        "Lithium\n(Zentrix Minerals)",
        "Cathode Plant\nMonterrey",
        "Cell Assembly\nAustin",
        "Pack Integration\nReno",
        "Electric Bus\nOEMs",
    ]
    img = Image.new("RGB", (1000, 260), WHITE)
    d = ImageDraw.Draw(img)
    d.text(
        (500, 30), "Acme Corp - Production Flow", font=font(24), fill=BLACK, anchor="mm"
    )
    for i, s in enumerate(steps):
        x = 20 + i * 196
        d.rounded_rectangle(
            [x, 90, x + 160, 190], radius=12, fill=GREY, outline=BLUE, width=3
        )
        d.multiline_text(
            (x + 80, 140), s, font=font(17), fill=BLACK, anchor="mm", align="center"
        )
        if i < len(steps) - 1:
            d.line([x + 162, 140, x + 194, 140], fill=BLACK, width=3)
            d.polygon([(x + 194, 140), (x + 184, 133), (x + 184, 147)], fill=BLACK)
    img.save(path)


def customer_pie(path):
    data = [
        ("Acme Corp", 45, BLUE),
        ("Volta Motors", 30, "#ed8936"),
        ("Others", 25, "#a0aec0"),
    ]
    img = Image.new("RGB", (700, 420), WHITE)
    d = ImageDraw.Draw(img)
    d.text(
        (350, 30),
        "Zentrix Minerals - 2025 Sales by Customer",
        font=font(24),
        fill=BLACK,
        anchor="mm",
    )
    start = -90
    for i, (name, pct, color) in enumerate(data):
        end = start + pct * 3.6
        d.pieslice([60, 80, 360, 380], start, end, fill=color, outline=WHITE, width=2)
        start = end
        d.rectangle([420, 150 + i * 50, 450, 180 + i * 50], fill=color)
        d.text(
            (465, 165 + i * 50),
            f"{name}: {pct}%",
            font=font(22),
            fill=BLACK,
            anchor="lm",
        )
    img.save(path)


PDF_HTML = """
<h1>Acme Corp Annual Report 2025</h1>

<h2>1. Company Overview</h2>
<p>Acme Corp manufactures lithium-ion battery packs for electric buses and is headquartered in
Austin, Texas. The company was founded in 2011 by Maria Okafor, who still serves as Chief Executive
Officer. Acme employs 4,200 people across three plants. In FY2025 Acme shipped 8,400 battery packs,
a 41% increase over the 5,960 packs shipped in FY2024.</p>

<p><b>Table 1: Financial Summary (USD millions unless stated)</b></p>
<table class="grid">
<tr><th>Metric</th><th>FY2023</th><th>FY2024</th><th>FY2025</th></tr>
<tr><td>Revenue</td><td>612</td><td>798</td><td>1,134</td></tr>
<tr><td>Operating margin</td><td>6.1%</td><td>7.4%</td><td>9.8%</td></tr>
<tr><td>R&amp;D spend</td><td>48</td><td>63</td><td>91</td></tr>
<tr><td>Net income</td><td>21</td><td>39</td><td>77</td></tr>
</table>

<p>Figure 1 shows how shipments grew through the year as the Reno line reached full capacity.</p>
<img src="shipments.png" width="460"/>

<h2>2. Supply Chain</h2>
<p>Lithium carbonate is our most critical input. Seventy percent of our lithium is sourced from
Zentrix Minerals under a long-term contract; the remainder comes from Borealis Chemicals. The table
below lists our key suppliers.</p>

<p><b>Table 2: Key Suppliers</b></p>
<table class="plain">
<tr><th>Supplier</th><th>Material</th><th>Share of supply</th><th>Contract ends</th></tr>
<tr><td>Zentrix Minerals</td><td>Lithium carbonate</td><td>70%</td><td>Dec 2027</td></tr>
<tr><td>Borealis Chemicals</td><td>Lithium carbonate</td><td>30%</td><td>Jun 2026</td></tr>
<tr><td>Halden Metals</td><td>Nickel sulfate</td><td>100%</td><td>Mar 2028</td></tr>
<tr><td>Corvo Polymers</td><td>Separator film</td><td>85%</td><td>Sep 2026</td></tr>
</table>

<p>Figure 2 shows our production flow from raw material to customer.</p>
<img src="process.png" width="480"/>

<h2>3. Risk Factors</h2>
<p>Our largest supply-chain risk is concentration: a single supplier provides the majority of our
lithium. Any disruption to that supplier's mining operations, whether operational or regulatory,
would directly reduce our production capacity. We are evaluating a second-source agreement for 2027.</p>
"""

PDF_CSS = """
body { font-family: sans-serif; font-size: 10pt; }
h1 { font-size: 18pt; } h2 { font-size: 13pt; }
table { border-collapse: collapse; margin-bottom: 8pt; }
th, td { padding: 3pt 8pt; text-align: left; }
table.grid th, table.grid td { border: 1px solid black; }
"""


def build_pdf(img_dir, path):
    story = pymupdf.Story(
        PDF_HTML, user_css=PDF_CSS, archive=pymupdf.Archive(str(img_dir))
    )
    writer = pymupdf.DocumentWriter(str(path))
    page = pymupdf.paper_rect("a4")
    more = True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(page + (50, 50, -50, -50))
        story.draw(dev)
        writer.end_page()
    writer.close()


def build_docx(img_dir, path):
    doc = Document()
    doc.add_heading("Zentrix Minerals - Supplier Profile", 0)
    doc.add_heading("Overview", 1)
    doc.add_paragraph(
        "Zentrix Minerals is a lithium producer headquartered in Perth, Australia. All of its active "
        "mines are located in Valdoria. In November 2025 the Valdorian government announced export "
        "restrictions on lithium, effective 1 March 2026: exports of lithium carbonate are capped at "
        "50% of each producer's 2025 volume."
    )
    doc.add_heading("Mine Sites", 1)
    rows = [
        ("Mine", "Region", "Annual output (tonnes)", "Status"),
        ("Valdoria North", "Valdoria", "18,000", "Active"),
        ("Valdoria South", "Valdoria", "9,000", "Active"),
        ("Kestrel Ridge", "Western Australia", "0", "Commissioning 2027"),
    ]
    table = doc.add_table(rows=len(rows), cols=4, style="Table Grid")
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            table.cell(r, c).text = val
    doc.add_heading("Customers", 1)
    doc.add_paragraph("The chart below shows the split of 2025 sales by customer.")
    doc.add_picture(str(img_dir / "customers.png"), width=Inches(5))
    doc.add_heading("Contacts", 1)
    # Synthetic PII for testing M6 masking (.example domain and 555 number are reserved for fiction).
    doc.add_paragraph(
        "Account manager: Daniel Reyes, daniel.reyes@zentrix.example, +1-555-0142."
    )
    doc.save(str(path))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        shipments_chart(tmp / "shipments.png")
        process_diagram(tmp / "process.png")
        customer_pie(tmp / "customers.png")
        build_pdf(tmp, OUT / "Acme_Annual_Report_2025.pdf")
        build_docx(tmp, OUT / "Zentrix_Supplier_Profile.docx")
    print(
        "wrote", *sorted(p.name for p in OUT.iterdir() if p.suffix in {".pdf", ".docx"})
    )
