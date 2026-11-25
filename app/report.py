"""Génération du rapport PDF d'attestation de contrôle (reportlab, 100 % Python)."""
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

# Palette corporate
GREEN, BLACK, GREY_D, GREY_M, GREY_L = (HexColor(h) for h in
                                        ("#369125", "#000000", "#646464", "#BBBBBB", "#F0F0F0"))
MINT, WINE, TAN, BROWN = (HexColor(h) for h in ("#90D5AC", "#9A4856", "#AD7F66", "#6D3828"))

STATE_LABEL = {"expired": "Expiré", "revoked": "Révoqué", "critical": "Critique",
               "warning": "À surveiller", "valid": "Valide", "nodate": "Sans date"}
STATE_COLOR = {"expired": WINE, "revoked": WINE, "critical": BROWN,
               "warning": TAN, "valid": GREEN, "nodate": GREY_D}
STATE_ORDER = {"expired": 0, "revoked": 1, "critical": 2, "warning": 3, "valid": 4, "nodate": 5}
CAT_LABEL = {"certificate": "Certificat", "license": "Licence", "domain": "Domaine"}
SCOPE_LABEL = {"": "certificats, licences et domaines", "certificate": "certificats",
               "license": "licences", "domain": "noms de domaine"}

_base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12, textColor=BLACK)
S = {
    "h1": ParagraphStyle("h1", parent=_base, fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=GREEN),
    "sub": ParagraphStyle("sub", parent=_base, fontSize=10, textColor=GREY_D),
    "h2": ParagraphStyle("h2", parent=_base, fontName="Helvetica-Bold", fontSize=12, leading=16,
                         textColor=GREEN, spaceBefore=12, spaceAfter=6, keepWithNext=1),
    "body": _base,
    "cell": ParagraphStyle("cell", parent=_base, fontSize=8, leading=10),
    "cellb": ParagraphStyle("cellb", parent=_base, fontSize=8, leading=10, fontName="Helvetica-Bold"),
    "head": ParagraphStyle("head", parent=_base, fontSize=8, leading=10, fontName="Helvetica-Bold"),
    "headw": ParagraphStyle("headw", parent=_base, fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=white),
    "mono": ParagraphStyle("mono", parent=_base, fontName="Courier", fontSize=8, leading=10),
}


def P(text, style="cell"):
    return Paragraph(escape(str(text if text is not None else "")), S[style])


def fmt_date(iso):
    return "-".join(reversed(iso.split("-"))).replace("-", "/") if iso else "—"


def _clip(text, n=70):
    return text if len(text) <= n else text[:n - 1] + "…"


class _NumberedCanvas(canvas.Canvas):
    """Pied de page « Page x / y » + référence du rapport."""
    footer_text = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            w, h = landscape(A4)
            self.setStrokeColor(GREEN); self.setLineWidth(2.5)
            self.line(15 * mm, h - 11 * mm, w - 15 * mm, h - 11 * mm)
            self.setStrokeColor(GREY_M); self.setLineWidth(.5)
            self.line(15 * mm, 12 * mm, w - 15 * mm, 12 * mm)
            self.setFont("Helvetica", 7.5); self.setFillColor(GREY_D)
            self.drawString(15 * mm, 8 * mm, self.footer_text)
            self.drawRightString(w - 15 * mm, 8 * mm, f"Page {self._pageNumber} / {total}")
            super().showPage()
        super().save()


def _table(headers, rows, widths, state_col=None, header_bg=GREEN):
    data = [[P(h, "headw") for h in headers]] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, GREY_L]),
        ("LINEBELOW", (0, 0), (-1, -1), .25, GREY_M),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    t.setStyle(TableStyle(style))
    return t


def _state_cell(state):
    return Paragraph(f'<font color="#FFFFFF"><b>{STATE_LABEL[state]}</b></font>',
                     ParagraphStyle("st", parent=_base, fontSize=8, leading=10, alignment=1))


def build_pdf(meta: dict, items: list[dict]) -> bytes:
    """meta : report_id, generated_at (datetime tz-aware), fetched_at (datetime), controller, user,
    comment, category, tz_name, source, service_account, thresholds{critical,warning}, sha256"""
    ordered = sorted(items, key=lambda c: (STATE_ORDER[c["state"]], c["end_validity"] or "9999", c["name"].lower()))
    counts = {k: 0 for k in STATE_ORDER}
    for c in ordered:
        counts[c["state"]] += 1
    attention = [c for c in ordered if c["state"] in ("expired", "revoked", "critical", "warning")]
    scope = SCOPE_LABEL[meta["category"]]
    g, f = meta["generated_at"], meta["fetched_at"]
    crit, warn = meta["thresholds"]["critical"], meta["thresholds"]["warning"]

    W = landscape(A4)[0] - 30 * mm     # largeur utile
    story = [Paragraph("Rapport de contrôle des échéances", S["h1"]),
             Paragraph(f"Inventaire Mercator – {scope}", S["sub"]), Spacer(1, 8)]

    # --- attestation
    if attention:
        result = (f"Résultat : {counts['expired']} expiré(s), {counts['revoked']} révoqué(s), "
                  f"{counts['critical']} critique(s) (≤ {crit} jours), {counts['warning']} à surveiller "
                  f"(≤ {warn} jours) – action de renouvellement requise.")
    else:
        result = "Résultat : aucune échéance dépassée ni proche, aucune action de renouvellement requise."
    attest = Paragraph(
        f"<b>Attestation de contrôle.</b> Le contrôle des échéances des {escape(scope)} inscrits dans Mercator a été "
        f"effectué le <b>{g:%d/%m/%Y}</b> à <b>{g:%H:%M}</b> ({escape(meta['tz_name'])}) par "
        f"<b>{escape(meta['controller'])}</b>. Les <b>{len(items)}</b> éléments ont été lus en direct dans Mercator "
        f"(API REST) à {f:%H:%M:%S}, puis comparés à la date du jour et classés selon les seuils définis. "
        f"<br/><br/>{escape(result)}", S["body"])
    box = Table([[attest]], colWidths=[W])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GREY_L), ("LINEBEFORE", (0, 0), (0, -1), 4, GREEN),
                             ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                             ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [box, Spacer(1, 10)]

    # --- métadonnées
    rows = [
        ("Référence du rapport", meta["report_id"]),
        ("Date et heure du contrôle", f"{g:%d/%m/%Y %H:%M:%S} ({meta['tz_name']})"),
        ("Contrôle réalisé par", meta["controller"] + (f"  (session : {meta['user']})" if meta["user"] else "")),
        ("Périmètre", f"{scope} – {len(items)} élément(s)"),
        ("Source des données", f"{meta['source']}  –  lecture à {f:%d/%m/%Y %H:%M:%S}"),
        ("Compte de service", meta["service_account"] or "—"),
        ("Seuils d'alerte", f"Critique ≤ {crit} jours ; À surveiller ≤ {warn} jours"),
        ("Empreinte SHA-256 des données", meta["sha256"]),
    ]
    mt = Table([[P(k, "cellb"), P(v, "mono" if k.startswith("Empreinte") else "cell")] for k, v in rows],
               colWidths=[55 * mm, W - 55 * mm])
    mt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), .25, GREY_M), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [Paragraph("Informations du contrôle", S["h2"]), mt]

    # --- synthèse
    keys = ["expired", "critical", "warning", "valid", "revoked", "nodate"]
    cw = W / 7
    syn = Table([[P("Total", "headw")] + [P(STATE_LABEL[k], "headw") for k in keys],
                 [Paragraph(f"<b>{len(items)}</b>", ParagraphStyle("n", parent=_base, fontSize=16, leading=20, alignment=1))] +
                 [Paragraph(f"<b>{counts[k]}</b>", ParagraphStyle("n", parent=_base, fontSize=16, leading=20, alignment=1))
                  for k in keys]], colWidths=[cw] * 7)
    st = [("BACKGROUND", (0, 0), (0, 0), GREY_D), ("BOX", (0, 0), (-1, -1), .5, GREY_M),
          ("INNERGRID", (0, 0), (-1, -1), .5, white), ("ALIGN", (0, 0), (-1, -1), "CENTER")]
    st += [("BACKGROUND", (i + 1, 0), (i + 1, 0), STATE_COLOR[k]) for i, k in enumerate(keys)]
    syn.setStyle(TableStyle(st))
    story += [Paragraph("Synthèse", S["h2"]), syn]

    # --- points d'attention
    story.append(Paragraph("Points d'attention", S["h2"]))
    if attention:
        rows = []
        for c in attention:
            rows.append([P(_clip(c["name"]), "cellb"), P(CAT_LABEL[c["category"]]), P(c["type"] or "—"),
                         P(fmt_date(c["end_validity"])), P("—" if c["days_left"] is None else c["days_left"]),
                         _state_cell(c["state"]),
                         P("Vérifier le statut / remplacer" if c["state"] == "revoked" else "Renouveler")])
        t = _table(["Nom", "Catégorie", "Type", "Fin de validité", "Jours restants", "Échéance", "Action attendue"],
                   rows, [W * x for x in (.30, .10, .12, .11, .09, .12, .16)])
        t.setStyle(TableStyle([("BACKGROUND", (5, i + 1), (5, i + 1), STATE_COLOR[c["state"]])
                               for i, c in enumerate(attention)]))
        story.append(t)
    else:
        story.append(Paragraph("Aucun point d'attention.", S["body"]))

    # --- inventaire complet
    story.append(Paragraph("Inventaire contrôlé", S["h2"]))
    rows = [[P(_clip(c["name"]), "cellb"), P(CAT_LABEL[c["category"]]), P(c["type"] or "—"),
             P(fmt_date(c["start_validity"])), P(fmt_date(c["end_validity"])),
             P("—" if c["days_left"] is None else c["days_left"]), _state_cell(c["state"]),
             P(c["status_label"] or "—"),
             P(_clip(", ".join(x["name"] for x in c["logical_servers"]) or "—", 60)),
             P(_clip(", ".join(x["name"] for x in c["applications"]) or "—", 60))] for c in ordered]
    inv = _table(["Nom", "Catégorie", "Type", "Début", "Fin", "Jours", "Échéance", "Statut", "Serveurs", "Applications"],
                 rows, [W * x for x in (.19, .07, .09, .07, .07, .05, .09, .06, .16, .15)])
    inv.setStyle(TableStyle([("BACKGROUND", (6, i + 1), (6, i + 1), STATE_COLOR[c["state"]])
                             for i, c in enumerate(ordered)]))
    story.append(inv)

    # --- validation
    sig_w = (W - 10 * mm) / 2
    def sig(title, name):
        t = Table([[P(title, "cellb")], [P(f"Nom : {name}")], [P("Date :")], [P("Signature :")], [""]],
                  colWidths=[sig_w], rowHeights=[None, 16, 16, 16, 34])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .6, GREY_M), ("BACKGROUND", (0, 0), (-1, 0), GREY_L),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
        return t
    sigs = Table([[sig("Contrôleur", meta["controller"]), "", sig("Validation (responsable)", "")]],
                 colWidths=[sig_w, 10 * mm, sig_w])
    block = [Paragraph("Validation", S["h2"])]
    if meta["comment"].strip():
        block += [Paragraph(f"<b>Commentaire du contrôleur :</b> {escape(meta['comment'].strip())}", S["body"]),
                  Spacer(1, 8)]
    block += [sigs, Spacer(1, 6),
              Paragraph("Les données ayant servi à ce rapport sont archivées et leur empreinte SHA-256 ci-dessus permet "
                        "d'en vérifier l'intégrité.", S["sub"])]
    story.append(KeepTogether(block))

    buf = BytesIO()
    _NumberedCanvas.footer_text = (f"Réf. {meta['report_id']}  |  SHA-256 {meta['sha256'][:16]}…  |  "
                                   f"Généré le {g:%d/%m/%Y %H:%M}")
    doc = BaseDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                          topMargin=18 * mm, bottomMargin=17 * mm,
                          title=f"Rapport de contrôle {meta['report_id']}", author=meta["controller"],
                          subject="Contrôle des échéances – Mercator")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
