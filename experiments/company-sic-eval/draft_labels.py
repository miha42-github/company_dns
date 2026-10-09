#!/usr/bin/env python3
"""DRAFT hand-judged acceptable codes (plan sec. 8), written from each company's
lines of business, NOT from retrieval results (which would favour the system
under test). Needs pyarrow only (validates every code against the feathers).

    python3 draft_labels.py /path/to/company_dns/tmp

Writes `acceptable` + `labels_status: "draft"` into companies.json for the
companies below, keeping everything else. ISIC Rev.4 and NACE Rev.2 share their
four-digit classes, so one ISIC list also yields the NACE list (NN.NN form).
Japan SIC is not drafted yet. A reviewer should read `notes` and every code.
NACE Rev.2 is listed explicitly: its four-digit classes are NOT always the
ISIC ones (e.g. ISIC 2100 pharmaceuticals is NACE 21.10/21.20, ISIC 5820 software
publishing is NACE 58.21/58.29), so it cannot be derived from the ISIC list.
"""
import json, sys
from pathlib import Path
import pyarrow.feather as f

HERE = Path(__file__).parent
tmp = Path(sys.argv[1])
def codes(name, col="class_id"):
    t = f.read_table(tmp / name)
    return dict(zip(t.column(col).to_pylist(), t.column("embedding_text").to_pylist()))
US, ISIC, NACE = codes("us_flat_embedded.feather"), codes("isic_rev4_flat_embedded.feather"), codes("nace_rev2_flat_embedded.feather")

# name: (US SIC leaf codes, ISIC Rev.4 classes, note)
D = {
 "Apple Inc.": (["3571","3663","3651","7372","3577"], ["2620","2630","2640","5820"], "hardware first; software/services secondary"),
 "International Business Machines": (["7373","7371","7372","7374","8742","3571"], ["6201","6202","6311","5820","2620"], "now mostly software, consulting and IT services; filer code 3570 is a group, not a leaf"),
 "Amazon (company)": (["5961","7374","7812","5411"], ["4791","6311","5911","4711"], "retail, cloud (AWS), streaming/studios, grocery"),
 "Walt Disney Company": (["7812","4833","4841","7996","7822"], ["5911","5913","6020","9321"], "studios, broadcast/cable, parks"),
 "Honeywell": (["3724","3728","3822","3823","3829"], ["3030","2651","2790"], "aerospace plus building/industrial controls"),
 "Comcast": (["4841","4833","7812","4812","7996"], ["6110","6020","5911","6120","9321"], "cable/broadband, NBCUniversal media, parks"),
 "Cisco": (["3661","3669","7372","7373"], ["2630","5820"], "networking hardware plus software/security"),
 "Intel": (["3674","3679","3577"], ["2610","2620"], "CPUs, chipsets, memory"),
 "Walmart": (["5331","5399","5411","5912","5541"], ["4711","4719","4791","4730"], "discount/supercenters, grocery, pharmacy, fuel"),
 "Costco": (["5399","5331","5411","5541","5912"], ["4711","4719","4730"], "membership warehouse club; filer 5331"),
 "Johnson & Johnson": (["2834","3841","3842","2836"], ["2100","3250"], "pharma plus medtech"),
 "Pfizer": (["2834","2836","2833"], ["2100","7210"], "pharma and vaccines"),
 "Eli Lilly and Company": (["2834","2836","2833"], ["2100"], "pharma"),
 "JPMorgan Chase": (["6021","6211","6282","6162","6141"], ["6419","6612","6630","6492"], "universal bank; ISIC 6411 is central banking, not applicable"),
 "American Express": (["6141","6153","6021","7389"], ["6492","6419","6619"], "card issuer and network"),
 "Visa Inc.": (["7389","6099","7374"], ["6619","6311"], "payment network, not an issuer"),
 "Ford Motor Company": (["3711","3714","6159","6141"], ["2910","2930","6492"], "vehicles, parts, Ford Credit"),
 "General Motors": (["3711","3714","6141"], ["2910","2930","6492"], "vehicles, parts, GM Financial"),
 "Lockheed Martin": (["3761","3764","3769","3721","3812","3728"], ["3030","2651","2520"], "aeronautics, missiles, space, mission systems; filer 3760 is a group"),
 "General Dynamics": (["3731","3795","3721","3812","7373"], ["3011","3040","3030","6202"], "ships, combat vehicles, Gulfstream, IT"),
 "Caterpillar Inc.": (["3531","3532","3519","6159"], ["2824","2811","6492"], "construction/mining machinery, engines, Cat Financial"),
 "Chevron Corporation": (["2911","1311","5541","4922"], ["0610","0620","1920","4730"], "integrated oil and gas"),
 "Coca-Cola Company": (["2086","2087"], ["1104"], "soft drinks and syrups; filer 2080 is a group"),
 "PepsiCo": (["2086","2096","2043","2087"], ["1104","1079","1061"], "beverages plus snacks and Quaker foods"),
 "Procter & Gamble": (["2844","2842","2841","2676","3421"], ["2023","1709"], "household and personal care; filer 2840 is a group"),
 "McDonald's": (["5812","6794"], ["5610"], "restaurants and franchising"),
 "Starbucks": (["5812","2095"], ["5610","1079"], "cafes plus packaged coffee; filer 5810 is a group"),
 "Nike, Inc.": (["3021","3149","2329","5139"], ["1520","1410","4641"], "footwear and apparel; filer 3021"),
 "Verizon": (["4813","4812","4899"], ["6110","6120"], "wireline and wireless"),
 "T-Mobile US": (["4812","4813"], ["6120","6110"], "wireless first"),
 "Marathon Petroleum": (["2911","5172","4613"], ["1920","4930","4661"], "refining, marketing, midstream"),
 "Sonos": (["3651","3663"], ["2640"], "consumer audio"),
 "Live Nation Entertainment": (["7922","7929","7941","7389","7999"], ["9000","7990","8230"], "concerts and ticketing; filer 7900 is a group"),
 "Booking Holdings": (["4724","4725","4729","7389"], ["7911","7990","7912"], "online travel; filer 4700 is a group"),
 "Kimberly-Clark": (["2676","2621","2679"], ["1709","1701"], "tissue and personal care paper products; filer 2670 is a group"),
 "Labcorp": (["8071","8731","8099"], ["8690","7210"], "clinical labs plus drug development services"),
 "HCA Healthcare": (["8062","8011","8093"], ["8610","8620"], "hospitals and outpatient care"),
}
NACE_PICKS = {
 "Apple Inc.": ["26.20","26.30","26.40","58.29"], "International Business Machines": ["62.01","62.02","63.11","58.29","26.20"],
 "Amazon (company)": ["47.91","63.11","59.11","47.11"], "Walt Disney Company": ["59.11","59.13","60.20","93.21"],
 "Honeywell": ["30.30","26.51","27.90","27.12"], "Comcast": ["61.10","60.20","59.11","61.20","93.21"],
 "Cisco": ["26.30","58.29"], "Intel": ["26.11","26.20"], "Walmart": ["47.11","47.19","47.91","47.30"],
 "Costco": ["47.11","47.19","47.30"], "Johnson & Johnson": ["21.20","32.50"], "Pfizer": ["21.20","21.10","72.11"],
 "Eli Lilly and Company": ["21.20","21.10"], "JPMorgan Chase": ["64.19","66.12","66.30","64.92"],
 "American Express": ["64.92","64.19","66.19"], "Visa Inc.": ["66.19","63.11"], "Ford Motor Company": ["29.10","29.32","64.92"],
 "General Motors": ["29.10","29.32","64.92"], "Lockheed Martin": ["30.30","26.51","25.40"],
 "General Dynamics": ["30.11","30.40","30.30","62.02"], "Caterpillar Inc.": ["28.92","28.11","64.92"],
 "Chevron Corporation": ["06.10","06.20","19.20","47.30"], "Coca-Cola Company": ["11.07"], "PepsiCo": ["11.07","10.89","10.61"],
 "Procter & Gamble": ["20.41","20.42","17.22"], "McDonald's": ["56.10"], "Starbucks": ["56.10","10.83"],
 "Nike, Inc.": ["15.20","14.13","14.19"], "Verizon": ["61.10","61.20"], "T-Mobile US": ["61.20","61.10"],
 "Marathon Petroleum": ["19.20","49.50","46.71"], "Sonos": ["26.40"], "Live Nation Entertainment": ["90.01","90.02","79.90","82.30"],
 "Booking Holdings": ["79.11","79.12","79.90"], "Kimberly-Clark": ["17.22","17.12","17.29"], "Labcorp": ["86.90","72.19"],
 "HCA Healthcare": ["86.10","86.21","86.22"],
}
path = HERE / "companies.json"
data = json.loads(path.read_text())
by = {c["name"]: c for c in data["companies"]}
problems = []
for name, (us, isic, note) in D.items():
    if name not in by:
        problems.append(f"not in set: {name}"); continue
    for c in us:
        if c not in US: problems.append(f"{name}: US {c} not in corpus")
    for c in isic:
        if c not in ISIC: problems.append(f"{name}: ISIC {c} not in corpus")
    nace = NACE_PICKS[name]
    for c in nace:
        if c not in NACE: problems.append(f"{name}: NACE {c} not in corpus")
    rec = by[name]
    rec["acceptable"] = {"us_sic": [c for c in us if c in US], "isic_rev4": [c for c in isic if c in ISIC],
                         "nace_rev2": [c for c in nace if c in NACE]}
    rec["labels_status"] = "draft"
    rec["notes"] = note
path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
print(f"drafted {sum(1 for c in data['companies'] if c.get('labels_status')=='draft')} companies")
print("\n".join(problems) or "all codes exist in their corpora")
