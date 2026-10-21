import glob
import os
import re
import unicodedata
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter
from resume_documents import extract_candidate_name, parse_tailored_resume_document, source_sections

class ResumePDF(FPDF):
    def __init__(self, target_role=None):
        super().__init__()
        self.target_role = target_role
        self.unicode_font = self._register_unicode_font()
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(auto=True, margin=16)

    def _register_unicode_font(self):
        candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
        candidates.extend(glob.glob(os.path.join(os.path.dirname(__file__), "fonts", "*.ttf")))
        font_path = next((path for path in candidates if os.path.isfile(path)), None)
        if not font_path:
            return False
        self.add_font("ResumeUnicode", fname=font_path)
        return True

    def set_resume_font(self, size):
        self.set_font("ResumeUnicode" if self.unicode_font else "Helvetica", size=size)

    def header(self):
        # The structured-document cover renders its identity and role header itself.
        return

    def _font_text(self, text):
        normalized = unicodedata.normalize("NFKC", str(text))
        # PDF extraction sometimes represents icon fonts as private-use glyphs;
        # those have no portable text meaning and render as missing-glyph boxes.
        normalized = "".join(char for char in normalized if unicodedata.category(char) != "Co")
        replacements = {
            "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
            "\u2014": "-", "\u2212": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"', "\u00a0": " ",
            "\ufeff": "",
        }
        for source, replacement in replacements.items():
            normalized = normalized.replace(source, replacement)
        if self.unicode_font:
            return normalized
        normalized = normalized.replace("\u2022", "-")
        return normalized.encode("latin-1", errors="replace").decode("latin-1")


def _write_text_line(pdf, text):
    safe_text = pdf._font_text(text)
    pdf.set_resume_font(10)
    pdf.set_text_color(25, 35, 50)
    pdf.multi_cell(0, 5, safe_text, new_x="LMARGIN", new_y="NEXT")


def _render_structured_resume(pdf, document):
    source_text = document["source_resume_text"]
    candidate_name = extract_candidate_name(source_text)
    email = next(
        (
            token.strip("<>()[]{};,\"'")
            for token in source_text.split()
            if token.count("@") == 1
            and token.rsplit("@", 1)[0]
            and "." in token.rsplit("@", 1)[1].strip("<>()[]{};,\"'")
        ),
        None,
    )
    phone = re.search(r"\+?\d[\d .()/-]{7,}\d", source_text)
    contact_items = [email] if email else []
    if phone:
        contact_items.append(phone.group().strip())

    pdf.set_resume_font(22)
    pdf.set_text_color(25, 45, 72)
    if candidate_name:
        pdf.cell(0, 11, pdf._font_text(candidate_name), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_resume_font(12)
    pdf.set_text_color(65, 80, 100)
    pdf.cell(0, 7, pdf._font_text(document["target_role"]), new_x="LMARGIN", new_y="NEXT", align="C")
    if contact_items:
        pdf.set_resume_font(9)
        pdf.cell(0, 6, pdf._font_text("  |  ".join(contact_items)), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)
    pdf.set_draw_color(180, 190, 205)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(7)

    if document["targeted_summary"]:
        pdf.set_resume_font(12)
        pdf.set_text_color(25, 65, 110)
        pdf.cell(0, 7, "ROLE-ALIGNED PROFILE", new_x="LMARGIN", new_y="NEXT")
        for excerpt in document["targeted_summary"]:
            _write_text_line(pdf, f"- {excerpt}")
    if document["highlighted_skills"]:
        pdf.ln(5)
        pdf.set_resume_font(12)
        pdf.set_text_color(25, 65, 110)
        pdf.cell(0, 7, "RELEVANT SKILLS", new_x="LMARGIN", new_y="NEXT")
        _write_text_line(pdf, "  ·  ".join(document["highlighted_skills"]))


def _render_source_text(pdf, source_text):
    for heading, lines in source_sections(source_text):
        if heading:
            if pdf.get_y() > pdf.h - pdf.b_margin - 14:
                pdf.add_page()
            pdf.ln(2)
            pdf.set_resume_font(11)
            pdf.set_text_color(25, 65, 110)
            pdf.cell(0, 6, pdf._font_text(heading), new_x="LMARGIN", new_y="NEXT")
        for line in lines:
            if not line.strip():
                pdf.ln(1)
                continue
            if pdf.get_y() > pdf.h - pdf.b_margin - 8:
                pdf.add_page()
            _write_text_line(pdf, line.strip())

def create_tailored_pdf(tailored_text, output_filename="tailored_resume.pdf", source_pdf_path=None):
    if isinstance(tailored_text, dict):
        document = tailored_text
    else:
        document = parse_tailored_resume_document(tailored_text) if isinstance(tailored_text, str) else None

    pdf = ResumePDF(target_role=document["target_role"] if document else None)
    pdf.add_page()
    if document:
        if document.get("schema_version") == 3:
            pdf.set_resume_font(9)
            pdf.set_text_color(65, 80, 100)
            pdf.cell(
                0,
                6,
                pdf._font_text(f"Tailored for {document['target_role']} | {document['target_company']}"),
                new_x="LMARGIN",
                new_y="NEXT",
                align="R",
            )
            pdf.set_draw_color(180, 190, 205)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)
            _render_source_text(pdf, document["final_resume_text"])
            pdf.output(output_filename)
            return output_filename
        if source_pdf_path and os.path.isfile(source_pdf_path):
            # Legacy v1/v2 records contain only emphasis snippets, not a full rewrite.
            # Do not staple those snippets onto the master and present them as a résumé.
            writer = PdfWriter()
            writer.append(PdfReader(source_pdf_path))
            with open(output_filename, "wb") as output_file:
                writer.write(output_file)
            return output_filename
        _render_structured_resume(pdf, document)
        _render_source_text(pdf, document["source_resume_text"])
    else:
        # Legacy tailored text remains renderable, but never gets a fabricated identity header.
        _render_source_text(pdf, str(tailored_text))

    pdf.output(output_filename)
    return output_filename