"""Starter bodies for the EC Templates compose editor.

Add a dict to DOCUMENT_STARTERS to grow the catalogue. Each starter is HTML
that is dropped into the on-page editor; save wraps it in the Society letterhead.
"""

from __future__ import annotations

from typing import Any

DOCUMENT_STARTERS: list[dict[str, Any]] = [
    {
        "id": "blank",
        "title": "Blank page",
        "description": "Empty writing area on Society letterhead.",
        "category": "correspondence",
        "tags": ["compose", "blank"],
        "suggestedTitle": "Untitled document",
        "bodyHtml": "<p></p>",
    },
    {
        "id": "resolution",
        "title": "Resolution",
        "description": "Certified true copy of an Executive Committee resolution.",
        "category": "correspondence",
        "tags": ["compose", "resolution", "ec"],
        "suggestedTitle": "Resolution — ",
        "bodyHtml": """
<p style="text-align:center"><strong>CERTIFIED TRUE COPY OF RESOLUTION</strong></p>
<p>Passed by the Executive Committee of Mandi Housing Welfare Society at its meeting held on
<strong>________</strong> at Housing Colony Sanyard, Mandi, Himachal Pradesh.</p>
<p>The Committee considered <strong>________</strong> and it was unanimously:</p>
<p><strong>RESOLVED THAT</strong> ________</p>
<p><strong>RESOLVED FURTHER THAT</strong> the President and the General Secretary be authorised
to do all acts necessary to give effect to this resolution, including correspondence with
authorities and the Society’s bankers.</p>
<p>Certified that the above is a true extract of the resolution, that it is in force, and that it
has not been modified or rescinded.</p>
<p>Place: Mandi (H.P.) &nbsp;&nbsp; Date: ________</p>
<p>For Mandi Housing Welfare Society</p>
<p>________________________ &nbsp;&nbsp;&nbsp; ________________________<br>
Anup Vaidya, President &nbsp;&nbsp;&nbsp; Vijay Kumar Sharma, General Secretary<br>
<em>(Society seal)</em></p>
""".strip(),
    },
    {
        "id": "resolution_engage_advocate_path",
        "title": "Resolution — engage advocate (path case)",
        "description": "Certified EC resolution to engage Advocate Shailesh Sharma for Court Case No. 01 (path / link road), professional fee ₹50,000.",
        "category": "correspondence",
        "tags": ["compose", "resolution", "ec", "legal", "advocate"],
        "suggestedTitle": "Resolution — engage Advocate Shailesh Sharma (path case)",
        "bodyHtml": """
<p style="text-align:center"><strong>CERTIFIED TRUE COPY OF RESOLUTION</strong></p>
<p>Passed by the Executive Committee of Mandi Housing Welfare Society at its meeting held on
<strong>________</strong> at Housing Colony Sanyard, Mandi, Himachal Pradesh.</p>
<p>The Committee noted that Civil Suit ≈ <strong>086/2023</strong> is pending before the learned
Senior Civil Judge, Mandi (Society Court Case No. 01), in which the Society / colony association
is a defendant, concerning the alleged right of path / link road through Himuda Housing Colony
Sanyardh (especially near Plot 12-A and Khasra 676/68). Further hearings remain. The Committee
considered the need to engage fresh counsel to take the matter forward, and the professional fee
agreed with Advocate <strong>Shailesh Sharma</strong>.</p>
<p>It was therefore unanimously:</p>
<p><strong>RESOLVED THAT</strong> Advocate <strong>Shailesh Sharma</strong> be and is hereby
engaged as advocate for Mandi Housing Welfare Society to appear, plead, act and take all
necessary steps on behalf of the Society in the said pending path / link-road civil suit and any
connected application in the same court, in supersession of any earlier engagement of counsel
for this matter to the extent a fresh vakalatnama is required.</p>
<p><strong>RESOLVED FURTHER THAT</strong> the professional fee of the said advocate for
conducting the case be and is hereby sanctioned at <strong>₹50,000 (Rupees Fifty Thousand
only)</strong>, to be paid from the Society’s Bank of Baroda account (No. 09640100004511,
IFSC BARB0MANDIX) by any two authorised signatories. Court fees, stamps, process, certified
copies and similar out-of-pocket expenses shall be paid by the Society separately against bills.</p>
<p><strong>RESOLVED FURTHER THAT</strong> the President and the General Secretary, jointly or
either of them, be authorised to execute the vakalatnama and all papers required to conduct the
case, and that the Treasurer be authorised to process the sanctioned fee and verified bills.</p>
<p>Certified that the above is a true extract of the resolution, that it is in force, and that it
has not been modified or rescinded.</p>
<p>Place: Mandi (H.P.) &nbsp;&nbsp; Date: ________</p>
<p>For Mandi Housing Welfare Society</p>
<p>________________________ &nbsp;&nbsp;&nbsp; ________________________<br>
Anup Vaidya, President &nbsp;&nbsp;&nbsp; Vijay Kumar Sharma, General Secretary<br>
<em>(Society seal)</em></p>
""".strip(),
    },
    {
        "id": "forwarding_letter",
        "title": "Forwarding letter",
        "description": "Cover note forwarding an enclosure to an office or bank.",
        "category": "correspondence",
        "tags": ["compose", "letter", "forwarding"],
        "suggestedTitle": "Forwarding letter — ",
        "bodyHtml": """
<p>No. MHWS/________/2026/________ &nbsp;&nbsp;&nbsp; Date: ________<br>
Place: Mandi (H.P.)</p>
<p>To<br>
The ________________<br>
________________<br>
________________</p>
<p><strong>Subject:</strong> Forwarding of ________ — Mandi Housing Welfare Society
(Registration No. 467 dated 21/07/2012).</p>
<p>Sir / Madam,</p>
<p>Please find enclosed herewith ________ in respect of Himuda Housing Colony Sanyard, Mandi,
for your kind information and necessary action.</p>
<p>The Society shall be glad to furnish any further particulars that may be required.</p>
<p>Yours faithfully,<br>
For Mandi Housing Welfare Society</p>
<p>________________________<br>
Name: ________ &nbsp;&nbsp; Designation: ________<br>
Mobile: ________</p>
<p>Encl.: As above</p>
""".strip(),
    },
    {
        "id": "covering_letter",
        "title": "Covering letter (bank / authority)",
        "description": "Formal covering letter, e.g. change of authorised signatories.",
        "category": "correspondence",
        "tags": ["compose", "letter", "bank"],
        "suggestedTitle": "Covering letter — Bank of Baroda",
        "bodyHtml": """
<p>No. MHWS/BoB/2026/________ &nbsp;&nbsp;&nbsp; Date: ________<br>
Place: Mandi (H.P.)</p>
<p>To<br>
The Branch Manager<br>
Bank of Baroda<br>
Mandi Branch<br>
Mandi, Himachal Pradesh 175001</p>
<p><strong>Subject:</strong> Change of authorised signatories — Account No. 09640100004511
(IFSC BARB0MANDIX) of Mandi Housing Welfare Society.</p>
<p>Sir / Madam,</p>
<p>Mandi Housing Welfare Society (Registration No. 467 dated 21/07/2012) maintains Account
No. <strong>09640100004511</strong> with your Branch. A new Executive Committee has assumed charge.</p>
<p>In supersession of all earlier mandates, you are requested to record the following four office
bearers as authorised signatories, and to honour cheques and instructions signed jointly by
<strong>any two</strong> of them:</p>
<ol>
<li>President — Anup Vaidya (94184 95449)</li>
<li>Vice President — Murari Lal Modgil (94181 68784)</li>
<li>General Secretary — Vijay Kumar Sharma (82197 88139)</li>
<li>Treasurer — Parveen Kumar Thakur (94180 71187)</li>
</ol>
<p>A certified copy of the resolution is enclosed. We shall complete specimen-signature cards
and KYC as required by the Branch.</p>
<p>Yours faithfully,<br>
For Mandi Housing Welfare Society</p>
<p>________________________ &nbsp;&nbsp;&nbsp; ________________________<br>
Anup Vaidya, President &nbsp;&nbsp;&nbsp; Vijay Kumar Sharma, General Secretary</p>
<p>Encl.: Resolution · Specimen signatures · KYC</p>
""".strip(),
    },
    {
        "id": "notice",
        "title": "Colony notice",
        "description": "Notice for the board, portal, or circulation to plot owners.",
        "category": "notice",
        "tags": ["compose", "notice"],
        "suggestedTitle": "Notice — ",
        "bodyHtml": """
<p style="text-align:center"><strong>NOTICE</strong></p>
<p>No. MHWS/N/2026/________ &nbsp;&nbsp;&nbsp; Date: ________</p>
<p>To all plot owners / residents of Himuda Housing Colony Sanyard</p>
<p>Notice is hereby given that ________</p>
<p><strong>Date / time:</strong> ________<br>
<strong>Place:</strong> ________<br>
<strong>Purpose:</strong> ________</p>
<p>All concerned are requested to take note and cooperate.</p>
<p>By order of the Executive Committee<br>
Mandi Housing Welfare Society</p>
<p>________________________<br>
Vijay Kumar Sharma, General Secretary<br>
Mobile: 82197 88139</p>
""".strip(),
    },
    {
        "id": "circular",
        "title": "Circular",
        "description": "Internal circular to office bearers / members / staff.",
        "category": "notice",
        "tags": ["compose", "circular"],
        "suggestedTitle": "Circular — ",
        "bodyHtml": """
<p style="text-align:center"><strong>CIRCULAR</strong></p>
<p>No. MHWS/C/2026/________ &nbsp;&nbsp;&nbsp; Date: ________</p>
<p>This circular is issued for information of ________</p>
<p>1. ________<br>
2. ________<br>
3. ________</p>
<p>This issues with the approval of the President / Executive Committee.</p>
<p>________________________<br>
General Secretary<br>
Mandi Housing Welfare Society</p>
""".strip(),
    },
    {
        "id": "mom_ec",
        "title": "Minutes (Executive Committee)",
        "description": "Short MOM of an EC meeting — agenda, discussion, decisions.",
        "category": "form",
        "tags": ["compose", "mom", "ec"],
        "suggestedTitle": "EC minutes — ",
        "bodyHtml": """
<p style="text-align:center"><strong>MINUTES OF THE EXECUTIVE COMMITTEE MEETING</strong></p>
<p>Mandi Housing Welfare Society · Himuda Housing Colony Sanyard<br>
Date: ________ &nbsp;&nbsp; Time: ________ &nbsp;&nbsp; Place: ________</p>
<p><strong>Present:</strong> ________<br>
<strong>Leave of absence:</strong> ________<br>
<strong>In the chair:</strong> Anup Vaidya, President</p>
<p><strong>1. Confirmation of previous minutes</strong><br>
The minutes of the meeting dated ________ were confirmed / confirmed with the following
correction: ________</p>
<p><strong>2. Agenda item</strong><br>
Discussion: ________<br>
Decision: ________<br>
Action: ________ &nbsp; By: ________ &nbsp; By date: ________</p>
<p><strong>3. Any other business</strong><br>
________</p>
<p>The meeting ended with a vote of thanks to the Chair.</p>
<p>________________________ &nbsp;&nbsp;&nbsp; ________________________<br>
Recorded by, General Secretary &nbsp;&nbsp;&nbsp; Confirmed by, President</p>
""".strip(),
    },
    {
        "id": "mom_gh",
        "title": "Minutes (General House)",
        "description": "Short MOM of a General House / GBM.",
        "category": "form",
        "tags": ["compose", "mom", "general house"],
        "suggestedTitle": "General House minutes — ",
        "bodyHtml": """
<p style="text-align:center"><strong>MINUTES OF THE GENERAL HOUSE / GENERAL BODY MEETING</strong></p>
<p>Mandi Housing Welfare Society · Himuda Housing Colony Sanyard<br>
Date: ________ &nbsp;&nbsp; Time: ________ &nbsp;&nbsp; Place: ________</p>
<p><strong>Quorum:</strong> ________ plots represented.<br>
<strong>In the chair:</strong> Anup Vaidya, President</p>
<p><strong>1. Welcome</strong><br>
________</p>
<p><strong>2. Accounts / report</strong><br>
________</p>
<p><strong>3. Resolutions placed before the House</strong><br>
Resolution: ________ &nbsp; Result: Carried / Not carried (votes: ________)</p>
<p><strong>4. Any other business</strong><br>
________</p>
<p>The House thanked the Chair and the meeting was declared closed.</p>
<p>________________________ &nbsp;&nbsp;&nbsp; ________________________<br>
General Secretary &nbsp;&nbsp;&nbsp; President</p>
""".strip(),
    },
    {
        "id": "agenda",
        "title": "Meeting agenda",
        "description": "Agenda paper for an EC or General House sitting.",
        "category": "form",
        "tags": ["compose", "agenda"],
        "suggestedTitle": "Agenda — ",
        "bodyHtml": """
<p style="text-align:center"><strong>AGENDA</strong></p>
<p>Meeting of: Executive Committee / General House<br>
Date: ________ &nbsp;&nbsp; Time: ________ &nbsp;&nbsp; Place: ________</p>
<ol>
<li>Confirmation of minutes of the previous meeting dated ________</li>
<li>________</li>
<li>________</li>
<li>________</li>
<li>Any other matter with the permission of the Chair</li>
</ol>
<p>Papers, if any, are enclosed / will be tabled.</p>
<p>________________________<br>
General Secretary<br>
Mandi Housing Welfare Society</p>
""".strip(),
    },
    {
        "id": "office_note",
        "title": "Office note",
        "description": "Internal note for the file — facts, proposal, orders.",
        "category": "correspondence",
        "tags": ["compose", "note"],
        "suggestedTitle": "Office note — ",
        "bodyHtml": """
<p style="text-align:center"><strong>OFFICE NOTE</strong></p>
<p>File / subject: ________ &nbsp;&nbsp; Date: ________</p>
<p><strong>1. Facts</strong><br>
________</p>
<p><strong>2. Rules / precedent</strong><br>
________</p>
<p><strong>3. Proposal</strong><br>
________</p>
<p><strong>4. Orders of the President / Committee</strong><br>
________</p>
<p>Put up for orders.<br>
________________________<br>
General Secretary / Treasurer</p>
""".strip(),
    },
]


def list_document_starters() -> list[dict[str, Any]]:
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "description": s.get("description") or "",
            "category": s.get("category") or "correspondence",
            "tags": list(s.get("tags") or []),
            "suggestedTitle": s.get("suggestedTitle") or s["title"],
            "bodyHtml": s["bodyHtml"],
        }
        for s in DOCUMENT_STARTERS
    ]


def starter_by_id(starter_id: str) -> dict[str, Any] | None:
    key = (starter_id or "").strip().lower()
    for item in list_document_starters():
        if item["id"] == key:
            return item
    return None
