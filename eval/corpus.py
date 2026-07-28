"""Labeled evaluation corpus.

Twenty-four short documents across the five supported doc types, plus
queries with known-relevant documents. Written to exercise the failure modes
that matter for legal retrieval rather than to be easy:

  - **Vocabulary mismatch.** Queries use the words a lawyer would type;
    documents use the words an inspector or an insurer wrote. "asbestos"
    against "friable ACM in pipe lagging". This is what the lexicon exists
    for.
  - **Near-duplicate documents.** Several disclosures differ only in party
    and address. This is Document-Level Retrieval Mismatch (arXiv
    2510.06999), the dominant legal RAG failure, and what contextual
    enrichment is supposed to mitigate.
  - **Distractors.** Documents that share vocabulary with a query but are
    not responsive to it.
  - **Multi-client.** Two client ids, so isolation failures show up as
    retrieval errors rather than staying invisible.

Small enough to read, large enough that ranking differences are visible.
It is a smoke test for the architecture, not a benchmark — treat the
relative comparisons as meaningful and the absolute numbers as not.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalDoc:
    doc_key: str
    filename: str
    client_id: str
    matter_id: str
    text: str


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    text: str
    client_id: str
    relevant: tuple[str, ...]
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


DOCS: list[EvalDoc] = [
    # ---------------------------------------------------------- ACME
    EvalDoc(
        "pd_elm", "seller_disclosure_elm.pdf", "ACME", "M1",
        """RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT

Seller: ACME Housing LLC. Buyer: Margaret Chen.
Property: 123 Elm Street, Hartford, CT 06103. Parcel H-1234.
Execution date: 2024-06-01.

Known hazards: friable ACM was identified in the pipe lagging serving the
basement boiler. The material has not been abated. Seller also notes
recurring moisture intrusion at the northeast foundation corner following
heavy rain.""",
    ),
    EvalDoc(
        "pd_oak", "seller_disclosure_oak.pdf", "ACME", "M2",
        """RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT

Seller: Riverbend Holdings LP. Buyer: ACME Housing LLC.
Property: 88 Oak Terrace, Stamford, CT 06902. Parcel S-9981.
Execution date: 2023-11-14.

Known hazards: none disclosed. Seller states no knowledge of hazardous
materials. Roof replaced 2019. No prior insurance claims reported.""",
    ),
    EvalDoc(
        "pd_maple", "seller_disclosure_maple.pdf", "ACME", "M3",
        """RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT

Seller: Delia Okonkwo. Buyer: ACME Housing LLC.
Property: 41 Maple Ridge Road, Fairfield, CT 06824. Parcel F-3310.
Execution date: 2024-02-20.

Known hazards: deteriorated lead-based paint on original window casings,
dwelling constructed 1948. Radon short-term test measured 5.1 pCi/L in the
finished basement. No mitigation system installed.""",
    ),
    EvalDoc(
        "esa_elm", "PhaseI_ESA_elm.pdf", "ACME", "M1",
        """PHASE I ENVIRONMENTAL SITE ASSESSMENT

Prepared by Coastal Environmental Group for ACME Housing LLC under ASTM
E1527-21. Subject property: 123 Elm Street, Hartford, Connecticut.

A recognized environmental condition was identified associated with a
former 550-gallon underground storage tank removed in 1987 without
documented closure sampling. Historical Sanborn maps show an automotive
service use from 1946 to 1979.

Conclusions: further investigation is warranted. A Phase II subsurface
investigation is recommended prior to acquisition.""",
    ),
    EvalDoc(
        "esa2_elm", "PhaseII_ESA_elm.pdf", "ACME", "M1",
        """PHASE II SUBSURFACE INVESTIGATION

Property: 123 Elm Street, Hartford, Connecticut.

Eight soil borings and three monitoring wells were installed. Groundwater
analytical results identified total petroleum hydrocarbons at 2,410 ug/L
and benzene at 41 ug/L, both exceeding CTDEEP Volatilization Criteria.

Soil sampling adjacent to the former tank grave detected lead at 940 mg/kg,
above the Residential Direct Exposure Criteria. Remediation will be
required prior to residential reuse.""",
    ),
    EvalDoc(
        "insp_elm", "home_inspection_elm.pdf", "ACME", "M1",
        """HOME INSPECTION REPORT

Inspector: Daniel Ruiz, CT License HOI-4471, Ruiz Building Consultants.
Inspection date: 2024-05-18. Property: 123 Elm Street, Hartford CT.

Structural: foundation sound, minor efflorescence noted northeast corner
consistent with periodic water entry.
Electrical: original knob-and-tube wiring remains active in the attic. This
is a safety concern and should be evaluated by a licensed electrician.
Plumbing: galvanized supply lines showing corrosion.

Hazardous materials observed: suspect asbestos-containing wrap on heating
distribution piping in the basement. Testing recommended before any
disturbance.""",
    ),
    EvalDoc(
        "insp_maple", "home_inspection_maple.pdf", "ACME", "M3",
        """HOME INSPECTION REPORT

Inspector: Priya Raman, CT License HOI-2298.
Inspection date: 2024-01-30. Property: 41 Maple Ridge Road, Fairfield CT.

Roof: three-tab shingles at end of service life, granule loss widespread,
replacement recommended within two years.
Exterior: chalking and flaking paint on window trim, consistent with
pre-1978 coatings. Lead testing recommended.
Interior: no visible microbial growth. Basement dry at time of inspection.""",
    ),
    EvalDoc(
        "claim_elm", "claim_elm_water.pdf", "ACME", "M1",
        """PROPERTY LOSS CLAIM FILE

Claim number CLM-2024-88213. Policy number HO-4471902.
Insured: ACME Housing LLC. Insurer: Charter Mutual Casualty.
Date of loss: 2024-03-02. Reported: 2024-03-04.
Loss location: 123 Elm Street, Hartford, CT.

Peril: water damage from sustained groundwater seepage through the
foundation wall following a rain event.

Coverage position: the carrier asserts a reservation of rights citing the
policy's surface water and seepage exclusion, which bars loss caused by
water below the surface of the ground exerting pressure on foundations.""",
    ),
    EvalDoc(
        "claim_oak", "claim_oak_fire.pdf", "ACME", "M2",
        """PROPERTY LOSS CLAIM FILE

Claim number CLM-2023-51004. Policy number HO-2210553.
Insured: Riverbend Holdings LP. Insurer: Charter Mutual Casualty.
Date of loss: 2023-08-19.
Loss location: 88 Oak Terrace, Stamford, CT.

Peril: kitchen fire originating at a range hood.

Coverage position: claim accepted. Payment issued less the $2,500
deductible. No exclusions asserted, no reservation of rights.""",
    ),
    EvalDoc(
        "med_worker", "medical_summary_worker.pdf", "ACME", "M1",
        """MEDICAL RECORD SUMMARY

Patient identifier: R.T. (initials only). Date of service: 2024-04-11.
Provider: Hartford Occupational Pulmonary Associates.

Occupational history: patient reports twenty-two years as a steamfitter
performing maintenance on institutional boiler systems, including removal
of thermal pipe wrap without respiratory protection during the 1970s and
early 1980s.

Imaging shows bilateral pleural plaques with calcification. Impression:
findings consistent with prior amphibole exposure. Diagnosis J92.0.""",
    ),
    EvalDoc(
        "esa_stamford", "PhaseI_ESA_oak.pdf", "ACME", "M2",
        """PHASE I ENVIRONMENTAL SITE ASSESSMENT

Prepared by Coastal Environmental Group. Subject property: 88 Oak Terrace,
Stamford, Connecticut.

No recognized environmental conditions were identified. Historical use is
residential from original construction. No underground storage tanks were
observed or documented. No further investigation is recommended.""",
    ),
    EvalDoc(
        "insp_oak", "home_inspection_oak.pdf", "ACME", "M2",
        """HOME INSPECTION REPORT

Inspector: Daniel Ruiz, CT License HOI-4471.
Inspection date: 2023-10-02. Property: 88 Oak Terrace, Stamford CT.

Roof: replaced 2019, remaining service life estimated twenty years.
Electrical: modern breaker panel, no deficiencies observed.
Plumbing: copper supply throughout, no corrosion.
No hazardous materials observed. No safety concerns identified.""",
    ),
    EvalDoc(
        "claim_maple", "claim_maple_denial.pdf", "ACME", "M3",
        """PROPERTY LOSS CLAIM FILE

Claim number CLM-2024-90117. Policy number HO-7781234.
Insured: ACME Housing LLC. Insurer: Northgate Indemnity.
Date of loss: 2024-04-22.
Loss location: 41 Maple Ridge Road, Fairfield, CT.

Peril: interior microbial growth discovered behind bathroom wall.

Determination: claim denied. The carrier cites the fungi, wet rot and
bacteria exclusion, and further asserts the damage resulted from
long-term deterioration rather than a sudden and accidental event.""",
    ),
    EvalDoc(
        "corr_abate", "abatement_correspondence.pdf", "ACME", "M1",
        """CORRESPONDENCE

To: ACME Housing LLC
Re: 123 Elm Street, Hartford — thermal system insulation

Following bulk sampling, two of three samples from the basement
distribution piping returned chrysotile content above one percent. The
material is friable and in poor condition.

Abatement by a licensed contractor is required before renovation activity
that would disturb the material. Notification obligations apply.""",
    ),
    EvalDoc(
        "corr_deadline", "matter_deadline_notice.pdf", "ACME", "M1",
        """MATTER CORRESPONDENCE

Re: 123 Elm Street acquisition — schedule

Counsel for the seller has proposed extending the inspection contingency
period by fourteen days. Closing remains scheduled for the end of the
quarter. Please confirm whether the extension is acceptable.

No substantive findings are discussed in this letter.""",
    ),
    # ------------------------------------------------- BRIDGEPORT (other client)
    EvalDoc(
        "bp_pd", "bridgeport_disclosure.pdf", "BRIDGEPORT", "B1",
        """RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT

Seller: Harbor Point Trust. Buyer: Bridgeport Realty Partners.
Property: 7 Seaview Avenue, Bridgeport, CT 06604.

Known hazards: asbestos floor tile in the utility room, non-friable and
intact. Radon not tested. Prior basement flooding disclosed.""",
    ),
    EvalDoc(
        "bp_esa", "bridgeport_esa.pdf", "BRIDGEPORT", "B1",
        """PHASE I ENVIRONMENTAL SITE ASSESSMENT

Subject property: 7 Seaview Avenue, Bridgeport, Connecticut.

A recognized environmental condition was identified relating to
documented dry cleaning operations on the adjoining parcel from 1962 to
1994, with potential for chlorinated solvent vapor intrusion.""",
    ),
    EvalDoc(
        "bp_claim", "bridgeport_claim.pdf", "BRIDGEPORT", "B1",
        """PROPERTY LOSS CLAIM FILE

Claim number CLM-2024-11902. Policy number CP-9930012.
Insured: Bridgeport Realty Partners. Insurer: Charter Mutual Casualty.
Loss location: 7 Seaview Avenue, Bridgeport, CT.

Peril: wind damage to roof membrane during a named storm. Coverage
accepted subject to the named storm deductible.""",
    ),
    # ------------------------------------------------------------ distractors
    EvalDoc(
        "misc_hoa", "hoa_minutes.pdf", "ACME", "M2",
        """ASSOCIATION MEETING MINUTES

The board discussed landscaping contracts, the repainting of common
hallways, and a proposal to repave the visitor parking area. A motion to
increase monthly dues was tabled.

No environmental, insurance, or structural matters were raised.""",
    ),
    EvalDoc(
        "misc_survey", "boundary_survey.pdf", "ACME", "M1",
        """BOUNDARY SURVEY NARRATIVE

Property: 123 Elm Street, Hartford, CT. Parcel H-1234.

Monuments recovered at three corners. The easterly line runs N 12 degrees
E a distance of 118.4 feet to an iron pin. A utility easement of ten feet
runs along the northerly boundary in favor of the water company.

No structures encroach upon adjoining parcels.""",
    ),
    EvalDoc(
        "misc_appraisal", "appraisal_elm.pdf", "ACME", "M1",
        """APPRAISAL REPORT

Property: 123 Elm Street, Hartford, CT.

The subject was valued using the sales comparison approach with three
closed comparables within one mile. Adjustments were made for gross living
area and garage capacity. Indicated value: $412,000 as of 2024-05-01.

The appraiser did not conduct any environmental or hazardous materials
investigation.""",
    ),
    EvalDoc(
        "misc_title", "title_commitment.pdf", "ACME", "M1",
        """TITLE COMMITMENT

Property: 123 Elm Street, Hartford, CT. Parcel H-1234.

Schedule B exceptions include a recorded utility easement, a right of way
in favor of the adjoining parcel, and standard survey exceptions. Taxes are
paid current through the second installment.

No liens of record other than the mortgage to be discharged at closing.""",
    ),
    EvalDoc(
        "misc_lease", "commercial_lease.pdf", "BRIDGEPORT", "B1",
        """COMMERCIAL LEASE ABSTRACT

Premises: ground floor retail, 7 Seaview Avenue, Bridgeport.
Term: ten years with two five-year options.

Tenant shall indemnify and hold harmless the landlord from claims arising
out of tenant's use of the premises, excepting the landlord's gross
negligence. Tenant maintains commercial general liability coverage.""",
    ),
    EvalDoc(
        "misc_invoice", "contractor_invoice.pdf", "ACME", "M1",
        """CONTRACTOR INVOICE

Re: 123 Elm Street, Hartford.

Labor and materials for replacement of basement stair treads and
installation of a handrail. Permit fee included. Balance due upon receipt.

Work did not involve any insulation, piping, or below-grade excavation.""",
    ),
]


QUERIES: list[EvalQuery] = [
    EvalQuery(
        "q_asbestos", "asbestos in the pipe insulation", "ACME",
        ("pd_elm", "insp_elm", "corr_abate", "med_worker"),
        "Vocabulary mismatch: documents say friable ACM, pipe lagging, "
        "thermal wrap, chrysotile, amphibole — never the query phrasing.",
        ("lexicon", "vocabulary"),
    ),
    EvalQuery(
        "q_lead", "lead paint hazard", "ACME",
        ("pd_maple", "insp_maple", "esa2_elm"),
        "Documents say lead-based paint, pre-1978 coatings, and lead at "
        "940 mg/kg in soil.",
        ("lexicon",),
    ),
    EvalQuery(
        "q_water_excl", "insurer denied water damage citing an exclusion", "ACME",
        ("claim_elm", "claim_maple"),
        "Reservation of rights and denial both count as adverse coverage "
        "positions; the accepted claims must not outrank them.",
        ("clause",),
    ),
    EvalQuery(
        "q_moisture", "seller knew about water getting into the basement", "ACME",
        ("pd_elm", "insp_elm", "claim_elm"),
        "Semantic, not lexical: documents say moisture intrusion, "
        "efflorescence, groundwater seepage.",
        ("semantic",),
    ),
    EvalQuery(
        "q_phase2", "which properties require further environmental investigation", "ACME",
        ("esa_elm", "esa2_elm"),
        "The Stamford ESA is a near-identical document type with the "
        "opposite conclusion and must not be retrieved.",
        ("near_duplicate",),
    ),
    EvalQuery(
        "q_ust", "underground storage tank contamination", "ACME",
        ("esa_elm", "esa2_elm"),
        "",
        ("semantic",),
    ),
    EvalQuery(
        "q_exceedance", "sampling results above regulatory criteria", "ACME",
        ("esa2_elm",),
        "Documents say exceeding CTDEEP Volatilization Criteria and above "
        "Residential Direct Exposure Criteria.",
        ("vocabulary",),
    ),
    EvalQuery(
        "q_electrical", "unsafe electrical wiring", "ACME",
        ("insp_elm",),
        "Document says knob-and-tube, a term the query never uses.",
        ("vocabulary",),
    ),
    EvalQuery(
        "q_roof", "roof at end of its service life", "ACME",
        ("insp_maple",),
        "The Oak inspection also discusses the roof but says it was "
        "recently replaced — a lexical distractor.",
        ("distractor",),
    ),
    EvalQuery(
        "q_ror", "reservation of rights", "ACME",
        ("claim_elm",),
        "Exact clause term; BM25 should carry this one.",
        ("clause",),
    ),
    EvalQuery(
        "q_mold", "mold claim denial", "ACME",
        ("claim_maple",),
        "Document says fungi, wet rot and bacteria exclusion and "
        "microbial growth.",
        ("vocabulary", "clause"),
    ),
    EvalQuery(
        "q_exposure", "occupational exposure history", "ACME",
        ("med_worker",),
        "",
        ("semantic",),
    ),
    EvalQuery(
        "q_radon", "radon testing results", "ACME",
        ("pd_maple",),
        "",
        ("lexicon",),
    ),
    EvalQuery(
        "q_elm_all", "123 Elm Street Hartford", "ACME",
        ("pd_elm", "esa_elm", "esa2_elm", "insp_elm", "claim_elm",
         "corr_abate", "misc_survey", "misc_appraisal", "misc_title",
         "misc_invoice", "corr_deadline"),
        "Address lookup across a matter. Many documents share the address, "
        "so this measures recall breadth rather than precision.",
        ("address",),
    ),
    EvalQuery(
        "q_clean", "properties with no disclosed hazards", "ACME",
        ("pd_oak", "esa_stamford", "insp_oak"),
        "Negative-condition retrieval, which dense handles far better "
        "than BM25.",
        ("semantic", "negation"),
    ),
    EvalQuery(
        "q_bp_asbestos", "asbestos disclosure", "BRIDGEPORT",
        ("bp_pd",),
        "Same query vocabulary as the ACME asbestos query. If client "
        "isolation leaks, ACME documents surface here.",
        ("isolation",),
    ),
]


def corpus_stats() -> dict[str, int]:
    return {
        "documents": len(DOCS),
        "queries": len(QUERIES),
        "clients": len({d.client_id for d in DOCS}),
        "relevance_pairs": sum(len(q.relevant) for q in QUERIES),
    }
