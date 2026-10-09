// A tiny dependency-free PDF writer for text reports (the Industry Match report).
// Plain PDF 1.4: A4 pages, Helvetica and Helvetica-Bold (the PDF standard fonts, so nothing is
// embedded), WinAnsi text (Latin-1 plus common punctuation; anything else becomes "?"), word
// wrapping, automatic page breaks, and a footer with page numbers. Text only, which is all the
// report needs, and the PDF stays selectable and searchable.
//
//   const pdf = new SimplePdf({ footer: "company_dns" });
//   pdf.text("Title", { size: 20, bold: true });
//   pdf.text("Body text that wraps", { size: 10, indent: 12 });
//   const bytes = pdf.build();          // Uint8Array
//
// `measure(text, size, bold)` returns the width in points; in the browser it uses a canvas with
// Helvetica/Arial (same metrics), elsewhere it falls back to an average-width estimate.

(function (root) {
  // Characters outside Latin-1 that WinAnsi (cp1252) has at 0x80-0x9F.
  const CP1252 = {
    "€": 0x80, "‚": 0x82, "ƒ": 0x83, "„": 0x84, "…": 0x85, "†": 0x86, "‡": 0x87,
    "ˆ": 0x88, "‰": 0x89, "Š": 0x8a, "‹": 0x8b, "Œ": 0x8c, "Ž": 0x8e, "‘": 0x91,
    "’": 0x92, "“": 0x93, "”": 0x94, "•": 0x95, "–": 0x96, "—": 0x97, "˜": 0x98,
    "™": 0x99, "š": 0x9a, "›": 0x9b, "œ": 0x9c, "ž": 0x9e, "Ÿ": 0x9f,
  };

  function winAnsi(str) {
    let out = "";
    for (const ch of String(str)) {
      const c = ch.codePointAt(0);
      if (c === 0x09 || c === 0x0a || c === 0x0d) out += " ";
      else if (c >= 0x20 && c < 0x7f) out += ch;
      else if (c >= 0xa0 && c <= 0xff) out += ch;
      else if (CP1252[ch] !== undefined) out += String.fromCharCode(CP1252[ch]);
      else out += "?";
    }
    return out;
  }

  const esc = (s) => s.replace(/[\\()]/g, (c) => "\\" + c);

  function defaultMeasure(text, size, bold) {
    return text.length * size * (bold ? 0.56 : 0.52);
  }

  class SimplePdf {
    constructor(opts = {}) {
      this.W = opts.pageW || 595.28;
      this.H = opts.pageH || 841.89;
      this.margin = opts.margin || 50;
      this.measure = opts.measure || defaultMeasure;
      this.footer = opts.footer || "";
      this.title = opts.title || "";
      this.pages = [];
      this._newPage();
    }

    _newPage() {
      this.page = [];
      this.pages.push(this.page);
      this.y = this.margin; // distance from the top of the page
    }

    _ensure(height) {
      if (this.y + height > this.H - this.margin - 14) this._newPage(); // 14pt reserved for the footer
    }

    space(pts) {
      this.y += pts;
    }

    rule(gray = 0.75) {
      this._ensure(6);
      const y = this.H - this.y - 2;
      this.page.push(`${gray} G 0.6 w ${this.margin} ${y.toFixed(2)} m ${this.W - this.margin} ${y.toFixed(2)} l S`);
      this.y += 6;
    }

    // Wraps `str` to the page width and writes it. Returns the number of lines.
    text(str, o = {}) {
      const size = o.size || 10;
      const bold = !!o.bold;
      const lead = size * (o.leading || 1.35);
      const indent = o.indent || 0;
      const gray = o.gray === undefined ? 0 : o.gray;
      const maxW = this.W - 2 * this.margin - indent;
      const lines = [];
      for (const para of winAnsi(str).split("\n")) {
        let line = "";
        for (const word of para.split(" ")) {
          const cand = line ? line + " " + word : word;
          if (line && this.measure(cand, size, bold) > maxW) {
            lines.push(line);
            line = word;
          } else {
            line = cand;
          }
        }
        lines.push(line);
      }
      if (o.keepTogether) this._ensure(lines.length * lead);
      for (const l of lines) {
        this._ensure(lead);
        const y = this.H - this.y - size; // baseline
        this.page.push(`BT /${bold ? "F2" : "F1"} ${size} Tf ${gray} g ${(this.margin + indent).toFixed(2)} ${y.toFixed(2)} Td (${esc(l)}) Tj ET`);
        this.y += lead;
      }
      if (o.after) this.y += o.after;
      return lines.length;
    }

    build() {
      const n = this.pages.length;
      const footerSize = 8;
      // footers, now that the page count is known
      this.pages.forEach((p, i) => {
        const left = winAnsi(this.footer);
        const right = `Page ${i + 1} of ${n}`;
        const y = this.margin - 8;
        p.push(`BT /F1 ${footerSize} Tf 0.45 g ${this.margin} ${y} Td (${esc(left)}) Tj ET`);
        const rw = this.measure(right, footerSize, false);
        p.push(`BT /F1 ${footerSize} Tf 0.45 g ${(this.W - this.margin - rw).toFixed(2)} ${y} Td (${esc(right)}) Tj ET`);
      });

      const objs = []; // objs[k] is the body of object k+1
      objs.push("<< /Type /Catalog /Pages 2 0 R >>");
      const kids = this.pages.map((_, i) => `${5 + i * 2} 0 R`).join(" ");
      objs.push(`<< /Type /Pages /Kids [${kids}] /Count ${n} >>`);
      objs.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
      objs.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");
      this.pages.forEach((p, i) => {
        const stream = p.join("\n");
        objs.push(
          `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${this.W} ${this.H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${6 + i * 2} 0 R >>`
        );
        objs.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
      });
      objs.push(`<< /Title (${esc(winAnsi(this.title))}) /Producer (company_dns) >>`);

      let out = "%PDF-1.4\n%âãÏÓ\n";
      const offsets = [];
      objs.forEach((body, i) => {
        offsets.push(out.length);
        out += `${i + 1} 0 obj\n${body}\nendobj\n`;
      });
      const xref = out.length;
      out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
      offsets.forEach((o) => (out += String(o).padStart(10, "0") + " 00000 n \n"));
      out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R /Info ${objs.length} 0 R >>\nstartxref\n${xref}\n%%EOF\n`;

      const bytes = new Uint8Array(out.length);
      for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xff;
      return bytes;
    }
  }

  // In the browser, measure with a canvas (Helvetica and Arial share metrics).
  SimplePdf.canvasMeasure = function () {
    const ctx = document.createElement("canvas").getContext("2d");
    return (text, size, bold) => {
      ctx.font = `${bold ? "bold " : ""}${size}px Helvetica, Arial, sans-serif`;
      return ctx.measureText(text).width;
    };
  };

  if (typeof module !== "undefined" && module.exports) module.exports = SimplePdf;
  else root.SimplePdf = SimplePdf;
})(typeof window !== "undefined" ? window : globalThis);
