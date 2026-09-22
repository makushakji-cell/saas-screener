"""Universe and every tunable, each with its reasoning.

The model here is deliberately small. An earlier version blended three
valuation methods, scored five weighted components and reported a Rule of 40;
it was defensible but nobody could follow it. This version does one thing you
can check by hand:

    fair value = (peer P/E adjusted for growth) x expected earnings per share

and one judgment on top of it: is the market's mood pointing the same way?
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
DB_PATH = DATA / "screener.db"
WEB = ROOT / "web"

# SEC requires a descriptive User-Agent with a contact address on every request.
# https://www.sec.gov/os/webmaster-faq#developers
SEC_USER_AGENT = "Michael Kushakji kushakji.mi@northeastern.edu"
SEC_RATE_LIMIT = 10.0

# --------------------------------------------------------------------------
# The universe
# --------------------------------------------------------------------------
# AppFolio sells property-management software to small and mid-sized
# landlords, with payment processing layered on top. Its real competitors --
# RealPage, Yardi, Entrata, MRI -- are all privately held and file nothing, so
# the comparison set is built from listed companies that either sell into the
# same market or run the same kind of business.

UNIVERSE = [
    # ticker,  what it sells software to
    ("APPF", "Property managers and landlords"),
    ("CSGP", "Commercial real estate professionals"),
    ("ZG",   "Home buyers, sellers and renters"),
    ("ALRM", "Property security and smart buildings"),
    ("SMRT", "Rental smart-home hardware"),
    ("TTAN", "Plumbers, electricians and home services"),
    ("TOST", "Restaurants"),
    ("EVCM", "Small service businesses"),
    ("PCTY", "Small-business payroll and HR"),
    ("WEAV", "Dental and medical practices"),
    ("PCOR", "Construction firms"),
    ("TYL",  "City and state government"),
    ("VEEV", "Pharmaceutical companies"),
    ("GWRE", "Property and casualty insurers"),
    ("BLKB", "Nonprofits and schools"),
    ("QTWO", "Banks and credit unions"),
    ("NCNO", "Bank lending departments"),
    ("INTA", "Law and consulting firms"),
    ("WK",   "Corporate finance and compliance teams"),
    ("BSY",  "Civil engineers and infrastructure"),
    ("DOCS", "Doctors and healthcare professionals"),
    ("IOT",  "Truck fleets and industrial operations"),
]

SUBJECT = "APPF"

# --------------------------------------------------------------------------
# Value -- P/E divided by growth
# --------------------------------------------------------------------------
#   P/E per point of growth  =  forward P/E / revenue growth %
#
# A P/E on its own says nothing about whether a company is expensive: 40x is
# cheap for something compounding 30% and dear for something growing 3%.
# Dividing one by the other gives a single number that is comparable across
# the whole group -- what you pay per dollar of profit, per point of growth.
# Lower is cheaper. It is the classic PEG ratio.
#
# This replaced a regression of P/E on growth. The regression fit better
# (R-squared 0.46) and produced a fair value per share, but it could not be
# explained in a sentence, and a number nobody can defend is worth less than a
# cruder one they can. PEG needs no explanation beyond its own name.
#
# It needs positive expected earnings and positive growth. A company with
# either missing has no PEG and is scored on market sentiment alone.

# Scored against where this group actually sits rather than the textbook
# "PEG of 1.0 is fair value" -- that rule comes from slower-growth industrials
# and marks nearly all software expensive. The median here is about 1.45, which
# anchors the middle of the curve.
PEG_ANCHOR_MEDIAN = 1.45

# --------------------------------------------------------------------------
# Recommendation
# --------------------------------------------------------------------------
# Two inputs, deliberately: what the numbers say, and what everyone else
# thinks. They often disagree, and that disagreement is the interesting part.
RECOMMENDATION_MIX = {
    "value":     0.65,   # how far below fair value the shares trade
    "sentiment": 0.35,   # whether the market and the professionals are warm on it
}

# "Sentiment" is not just analysts. Where a share sits in its own 12-month
# range is the crowd voting with money, and short interest is the other side
# of that bet. Together they cover the opinion the market is actually acting on.
SENTIMENT_MIX = {
    "analysts":   0.50,  # published consensus rating
    "momentum":   0.30,  # position within the 52-week range
    "short_int":  0.20,  # percent of float sold short, inverted
}

BUY_THRESHOLD = 60.0
SELL_THRESHOLD = 40.0

# Each raw metric maps to 0-100 by linear interpolation between these points.
CURVES = {
    # P/E per point of growth. Lower is cheaper, so this curve descends.
    # 1.45 -- the group median -- sits at 50.
    "value":     [(0.55, 100), (0.9, 82), (1.2, 65), (1.45, 50),
                  (1.8, 33), (2.4, 15), (4.0, 0)],
    # Yahoo's consensus mean: 1.0 strong buy, 5.0 strong sell. Stretched over
    # 1.3-3.0 because the sell side almost never publishes below 3.
    "analysts":  [(1.0, 100), (1.5, 82), (2.0, 62), (2.5, 42), (3.0, 25), (4.0, 0)],
    # Position in the 52-week range, 0 = at the low, 100 = at the high.
    "momentum":  [(0, 10), (25, 32), (50, 55), (75, 78), (100, 95)],
    # Percent of float sold short. Low is a vote of confidence.
    "short_int": [(0, 90), (3, 72), (6, 55), (10, 38), (16, 18), (25, 0)],
}

# Below this many covering analysts the consensus is not a consensus. It still
# counts, but the company is flagged and the weight shifts to the other two.
THIN_COVERAGE = 4

# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------
CACHE_TTL_HOURS = 12
FETCH_WORKERS = 4
FETCH_DELAY = 0.6
EDGAR_FORMS = ("10-K", "10-Q")
EDGAR_KEEP_PER_FORM = 4
