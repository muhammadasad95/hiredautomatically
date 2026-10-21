import os
from fpdf import FPDF

class ResumePDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 8, 'Muhammad Asad', new_x="LMARGIN", new_y="NEXT", align='C')
        self.set_font('Helvetica', '', 10)
        self.cell(0, 5, 'Senior Software Engineer | IAM & Backend Architecture', new_x="LMARGIN", new_y="NEXT", align='C')
        self.ln(5)

def create_tailored_pdf(tailored_text, output_filename="tailored_resume.pdf"):
    pdf = ResumePDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    
    # Split text into lines and write to PDF
    lines = tailored_text.split('\n')
    for line in lines:
        if line.strip().startswith('-') or line.strip().startswith('•'):
            pdf.set_font("Helvetica", 'B', 10)
            pdf.multi_cell(0, 5, line.strip())
        else:
            pdf.set_font("Helvetica", size=10)
            pdf.multi_cell(0, 5, line)
        pdf.ln(1)
        
    pdf.output(output_filename)
    return output_filename