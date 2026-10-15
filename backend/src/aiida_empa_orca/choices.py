"""ORCA 6.1 suggestions for the molecular HF/DFT geometry interface.

These are editable suggestions, not a method/basis compatibility database.
Sources and scope: docs/geometry.md, "Documented choices". Keep the legacy
schema-1 lists in settings.py unchanged. Composite and double-hybrid methods
need their own input treatment and are deliberately absent here.
"""

# ORCA's simple-input keywords, grouped by exchange treatment. In particular,
# SCAN is SCANFUNC (SCAN also names a geometry procedure), and M06-2X is M062X.
PURE_DFT = (
    "PBE", "BP86", "BLYP", "OLYP", "GLYP", "XLYP", "PW91", "MPWPW",
    "MPWLYP", "RPBE", "REVPBE", "RPW86PBE", "PWP",
    "TPSS", "REVTPSS", "SCANFUNC", "RSCAN", "R2SCAN", "M06L", "LDA",
)
HYBRID_DFT = (
    "PBE0", "B3LYP", "B3LYP/G", "B1LYP", "O3LYP", "X3LYP", "B1P86",
    "B3P86", "B3PW91", "PW1PW", "MPW1PW", "MPW1LYP", "REVPBE0",
    "REVPBE38", "BHANDHLYP", "M06", "M062X", "PW6B95", "TPSSH", "TPSS0",
    "R2SCANH", "R2SCAN0", "R2SCAN50", "CAM-B3LYP", "LC-BLYP", "LC-PBE",
    "WB97", "WB97X",
)
METHODS = ("HF", *PURE_DFT, *HYBRID_DFT)

BASES = (
    "def2-SVP", "def2-SV(P)", "def2-TZVP", "def2-TZVP(-f)", "def2-TZVPP",
    "def2-QZVP", "def2-QZVPP", "def2-SVPD", "def2-TZVPD", "def2-TZVPPD",
    "def2-QZVPD", "def2-QZVPPD", "ma-def2-SVP", "ma-def2-SV(P)",
    "ma-def2-TZVP", "ma-def2-TZVP(-f)", "ma-def2-TZVPP", "ma-def2-QZVPP",
    "dhf-SVP", "dhf-SV(P)", "dhf-TZVP", "dhf-TZVPP", "dhf-QZVP", "dhf-QZVPP",
    "cc-pVDZ", "cc-pVTZ", "cc-pVQZ", "aug-cc-pVDZ", "aug-cc-pVTZ", "aug-cc-pVQZ",
    "pcseg-1", "pcseg-2", "pcseg-3", "aug-pcseg-1", "aug-pcseg-2", "aug-pcseg-3",
    "6-31G", "6-31G*", "6-31G**", "6-31+G*", "6-31+G**", "6-31++G**",
    "6-311G", "6-311G*", "6-311G**", "6-311+G*", "6-311+G**", "6-311++G**",
)
# J-fitting only: /JK and /C occupy different auxiliary slots in simple input.
AUXILIARY_BASES = ("def2/J", "AutoAux")
ECPS = ("none", "def2-ECP", "dhf-ECP")
SCF_CONVERGENCE = (
    "SloppySCF", "LooseSCF", "MediumSCF", "NormalSCF", "StrongSCF",
    "TightSCF", "VeryTightSCF", "ExtremeSCF",
)
OPTIMIZATION = ("LooseOpt", "NormalOpt", "TightOpt", "VeryTightOpt")
DISPERSION = ("default", "D3BJ", "D3ZERO", "D4")

MANUAL = "https://www.faccts.de/docs/orca/6.1/manual/contents/"
MANUAL_LINKS = {
    "Functionals": MANUAL + "modelchemistries/DensityFunctionalTheory.html",
    "Basis sets and ECPs": MANUAL + "essentialelements/basisset.html",
    "SCF thresholds": MANUAL + "essentialelements/scf.html",
    "Geometry thresholds": MANUAL + "structurereactivity/optimizations.html",
    "Dispersion": MANUAL + "modelchemistries/dispersioncorrections.html",
}
